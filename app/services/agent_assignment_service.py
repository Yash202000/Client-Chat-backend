from sqlalchemy.orm import Session
from sqlalchemy import and_
from app.models.team_membership import TeamMembership
from app.models.team import Team
from app.models.user import User
from app.models.conversation_session import ConversationSession
from app.schemas.conversation_session import ConversationSessionUpdate
from app.services import conversation_session_service, livekit_service
from app.services.connection_manager import manager
from datetime import datetime
from typing import Optional
import logging
import json

logger = logging.getLogger(__name__)


def find_available_agent(db: Session, team_name: str, company_id: int) -> Optional[User]:
    """
    Finds an available agent in the specified team using round-robin with priority.

    Args:
        db: Database session
        team_name: Name of the team (e.g., 'Support', 'Sales')
        company_id: Company ID for filtering

    Returns:
        User object if available agent found, None otherwise
    """
    # First find the team by name
    team = db.query(Team).filter(
        and_(
            Team.name == team_name,
            Team.company_id == company_id
        )
    ).first()

    if not team:
        logger.warning(f"Team '{team_name}' not found for company {company_id}")
        return None

    # Query for available team members
    available_membership = db.query(TeamMembership).join(User).filter(
        and_(
            TeamMembership.team_id == team.id,
            TeamMembership.company_id == company_id,
            TeamMembership.is_available == True,
            User.presence_status.in_(['online', 'available']),
            TeamMembership.current_session_count < TeamMembership.max_concurrent_sessions
        )
    ).order_by(
        TeamMembership.priority.desc(),  # Higher priority first
        TeamMembership.current_session_count.asc()  # Then least loaded
    ).first()

    if available_membership:
        return available_membership.user

    logger.warning(f"No available agents found in team '{team_name}' for company {company_id}")
    return None


async def assign_session_to_agent(
    db: Session,
    session_id: str,
    agent_user_id: int,
    company_id: int,
    reason: str = "handoff",
    team_name: str = "Support"
) -> ConversationSession:
    """
    Assigns a conversation session to a specific agent.

    Args:
        db: Database session
        session_id: Conversation session ID
        agent_user_id: User ID of the agent to assign to
        company_id: Company ID
        reason: Reason for the handoff
        team_name: Team name for tracking

    Returns:
        Updated ConversationSession object
    """
    logger.info(f"Assigning session {session_id} to agent {agent_user_id}")

    # Update the session
    session_update = ConversationSessionUpdate(
        assignee_id=agent_user_id,
        is_ai_enabled=False,  # Disable AI when human takes over
        status='assigned',
        waiting_for_agent=False,
        handoff_accepted_at=datetime.utcnow(),
        assigned_pool=team_name  # Store team name in assigned_pool field
    )

    updated_session = conversation_session_service.update_session(db, session_id, session_update)

    # Find the team
    team = db.query(Team).filter(
        and_(
            Team.name == team_name,
            Team.company_id == company_id
        )
    ).first()

    if team:
        # Increment the agent's current session count in team membership
        team_membership = db.query(TeamMembership).filter(
            and_(
                TeamMembership.user_id == agent_user_id,
                TeamMembership.team_id == team.id,
                TeamMembership.company_id == company_id
            )
        ).first()

        if team_membership:
            team_membership.current_session_count += 1
            db.commit()

    logger.info(f"Session {session_id} successfully assigned to agent {agent_user_id}")
    return updated_session


async def request_handoff(
    db: Session,
    session_id: str,
    reason: str,
    team_name: str = "Support",
    priority: str = "normal"
) -> dict:
    """
    Initiates a handoff request for a session.

    Args:
        db: Database session
        session_id: Conversation session ID
        reason: Reason for handoff
        team_name: Team to assign from
        priority: Priority level ('normal' or 'urgent')

    Returns:
        Dictionary with handoff status and agent info if available
    """
    logger.info(f"Handoff requested for session {session_id}, reason: {reason}, team: {team_name}")

    # Get the session
    session = conversation_session_service.get_session(db, session_id)
    if not session:
        logger.error(f"Session {session_id} not found")
        return {"status": "error", "message": "Session not found"}

    # Update session with handoff request
    session_update = ConversationSessionUpdate(
        handoff_requested_at=datetime.utcnow(),
        handoff_reason=reason,
        assigned_pool=team_name,  # Store team name
        waiting_for_agent=True,
        status='pending_agent_assignment',
        is_ai_enabled=False  # Stop AI responses during handoff
    )

    updated_session = conversation_session_service.update_session(db, session_id, session_update)

    # Try to find an available agent
    available_agent = find_available_agent(db, team_name, session.company_id)

    if available_agent:
        logger.info(f"Found available agent: {available_agent.id} ({available_agent.email})")

        # Create LiveKit room for voice call
        agent_name = f"{available_agent.first_name} {available_agent.last_name}".strip() if available_agent.first_name else available_agent.email
        customer_name = session.contact.name if session.contact and session.contact.name else "Customer"

        try:
            call_room = livekit_service.create_call_room(
                session_id=session_id,
                user_identity=f"user_{session_id}",
                agent_identity=f"agent_{available_agent.id}",
                user_name=customer_name,
                agent_name=agent_name
            )

            # Broadcast incoming call notification to the company channel
            # The frontend will filter by agent_id to show only to the intended agent
            call_notification = {
                "type": "incoming_call",
                "agent_id": available_agent.id,  # Frontend will filter by this
                "session_id": session_id,
                "customer_name": customer_name,
                "summary": reason,
                "priority": priority,
                "room_name": call_room["room_name"],
                "livekit_url": call_room["livekit_url"],
                "agent_token": call_room["agent_token"],
                "user_token": call_room["user_token"],
                "timestamp": datetime.utcnow().isoformat()
            }

            # Broadcast to company channel (more reliable - agent is always listening)
            await manager.broadcast_to_company(session.company_id, json.dumps(call_notification))
            logger.info(f"Broadcasted call notification to company {session.company_id} for agent {available_agent.id}")

            return {
                "status": "call_initiated",
                "agent_id": available_agent.id,
                "agent_name": agent_name,
                "session_id": session_id,
                "team_name": team_name,
                "room_name": call_room["room_name"],
                "livekit_url": call_room["livekit_url"],
                "user_token": call_room["user_token"]
            }
        except Exception as e:
            logger.error(f"Failed to create LiveKit room: {e}")
            # Fall back to text-based handoff
            return {
                "status": "agent_found",
                "agent_id": available_agent.id,
                "agent_name": agent_name,
                "session_id": session_id,
                "team_name": team_name,
                "error": "Voice call unavailable, text chat assigned"
            }
    else:
        logger.warning(f"No agents available for session {session_id}")
        return {
            "status": "no_agents_available",
            "session_id": session_id,
            "team_name": team_name,
            "message": "No agents currently available. Please provide callback information."
        }


async def release_agent_from_session(
    db: Session,
    session_id: str,
    agent_user_id: int,
    team_name: str,
    company_id: int
) -> None:
    """
    Releases an agent from a session (decrements their session count).

    Args:
        db: Database session
        session_id: Conversation session ID
        agent_user_id: User ID of the agent
        team_name: Team name
        company_id: Company ID
    """
    # Find the team
    team = db.query(Team).filter(
        and_(
            Team.name == team_name,
            Team.company_id == company_id
        )
    ).first()

    if team:
        team_membership = db.query(TeamMembership).filter(
            and_(
                TeamMembership.user_id == agent_user_id,
                TeamMembership.team_id == team.id,
                TeamMembership.company_id == company_id
            )
        ).first()

        if team_membership and team_membership.current_session_count > 0:
            team_membership.current_session_count -= 1
            db.commit()
            logger.info(f"Released agent {agent_user_id} from session {session_id}")


def handle_no_agents_available(session_id: str) -> dict:
    """
    Returns callback collection prompt when no agents are available.

    Args:
        session_id: Conversation session ID

    Returns:
        Dictionary with callback collection instructions
    """
    return {
        "status": "collect_callback",
        "session_id": session_id,
        "message": "I apologize, but all our agents are currently assisting other customers. May I collect your contact information so we can call you back shortly?",
        "prompt": "Please provide your name, phone number, and preferred callback time."
    }
