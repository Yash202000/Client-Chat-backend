from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.core.dependencies import get_db, get_current_user
from app.models.user import User
from app.services import conversation_session_service, agent_assignment_service, livekit_service, messaging_service, integration_service
from app.services.connection_manager import manager
from app.api.v1.endpoints.video_calls import get_livekit_token
from app.core.config import settings
import json
import logging

logger = logging.getLogger(__name__)
router = APIRouter()


class HandoffAcceptRequest(BaseModel):
    session_id: str


class HandoffRejectRequest(BaseModel):
    session_id: str
    reason: str = "agent_unavailable"


class HandoffEndRequest(BaseModel):
    session_id: str


@router.post("/accept")
async def accept_handoff(
    request: HandoffAcceptRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Agent accepts a handoff request and joins the LiveKit room with the customer.
    """
    logger.info(f"[HANDOFF ACCEPT] Agent {current_user.id} accepting handoff for session {request.session_id}")

    # Get the session
    session = conversation_session_service.get_session(db, request.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if not session.waiting_for_agent:
        raise HTTPException(status_code=400, detail="Session is not waiting for an agent")

    # Assign session to this agent
    updated_session = await agent_assignment_service.assign_session_to_agent(
        db=db,
        session_id=request.session_id,
        agent_user_id=current_user.id,
        company_id=current_user.company_id,
        reason="handoff_accepted",
        pool_name=session.assigned_pool or "support"
    )

    # Generate LiveKit token for the agent
    room_name = f"handoff_{request.session_id}_{current_user.id}"
    agent_token = get_livekit_token(room_name, current_user.email)

    # Notify the user's WebSocket to transition to LiveKit
    await manager.broadcast_to_session(
        request.session_id,
        json.dumps({
            "type": "agent_accepted",
            "agent_id": current_user.id,
            "agent_name": current_user.first_name or current_user.email,
            "room_name": room_name,
            "transition_to_livekit": True
        }),
        "agent"
    )

    logger.info(f"[HANDOFF ACCEPT] Session {request.session_id} assigned to agent {current_user.id}")

    return {
        "status": "accepted",
        "session_id": request.session_id,
        "room_name": room_name,
        "livekit_token": agent_token,
        "livekit_url": settings.LIVEKIT_URL,
        "customer_name": f"User-{request.session_id}"
    }


@router.post("/reject")
async def reject_handoff(
    request: HandoffRejectRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Agent rejects a handoff request. System will try to assign to another agent.
    """
    logger.info(f"[HANDOFF REJECT] Agent {current_user.id} rejecting handoff for session {request.session_id}")

    # Get the session
    session = conversation_session_service.get_session(db, request.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if not session.waiting_for_agent:
        raise HTTPException(status_code=400, detail="Session is not waiting for an agent")

    # Try to find another available agent
    pool_name = session.assigned_pool or "support"
    another_agent = agent_assignment_service.find_available_agent(
        db, pool_name, current_user.company_id
    )

    if another_agent and another_agent.id != current_user.id:
        # Found another agent - notify them
        logger.info(f"[HANDOFF REJECT] Found alternative agent {another_agent.id}")

        await manager.broadcast(
            json.dumps({
                "type": "handoff_request",
                "session_id": request.session_id,
                "agent_id": session.agent_id,
                "summary": f"Handoff from previous agent (reason: {request.reason})",
                "reason": "reassignment",
                "assigned_agent_id": another_agent.id
            }),
            str(current_user.company_id)
        )

        return {
            "status": "reassigned",
            "session_id": request.session_id,
            "new_agent_id": another_agent.id,
            "message": "Handoff reassigned to another agent"
        }
    else:
        # No other agents available - collect callback
        logger.warning(f"[HANDOFF REJECT] No alternative agents available for session {request.session_id}")

        await manager.broadcast_to_session(
            request.session_id,
            json.dumps({
                "type": "no_agents_available",
                "message": "All agents are currently busy. Please provide callback information."
            }),
            "agent"
        )

        return {
            "status": "no_agents_available",
            "session_id": request.session_id,
            "message": "No agents available. Callback collection initiated."
        }


@router.get("/pending")
def get_pending_handoffs(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get list of pending handoff requests for the current agent's company.
    """
    # Query sessions waiting for agent assignment
    pending_sessions = conversation_session_service.get_sessions_by_status(
        db,
        company_id=current_user.company_id,
        status="pending_agent_assignment",
        waiting_for_agent=True
    )

    handoffs = []
    for session in pending_sessions:
        handoffs.append({
            "session_id": session.conversation_id,
            "agent_id": session.agent_id,
            "reason": session.handoff_reason,
            "requested_at": session.handoff_requested_at.isoformat() if session.handoff_requested_at else None,
            "pool": session.assigned_pool,
            "assignee_id": session.assignee_id
        })

    return {"handoffs": handoffs, "count": len(handoffs)}


@router.post("/end")
async def end_handoff(
    request: HandoffEndRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Agent ends a handoff call. Decrements their session count to free up capacity.
    """
    logger.info(f"[HANDOFF END] Agent {current_user.id} ending handoff for session {request.session_id}")

    # Get the session
    session = conversation_session_service.get_session(db, request.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Only allow the assigned agent to end the call
    if session.assignee_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not assigned to this session")

    # Release agent (decrement session count) if assigned to a pool/team
    if session.assigned_pool:
        await agent_assignment_service.release_agent_from_session(
            db=db,
            session_id=request.session_id,
            agent_user_id=current_user.id,
            team_name=session.assigned_pool,
            company_id=current_user.company_id
        )
        logger.info(f"[HANDOFF END] Released agent {current_user.id} from pool {session.assigned_pool}")

    # Notify widget that call ended
    await manager.broadcast_to_session(
        request.session_id,
        json.dumps({
            "type": "call_ended",
            "ended_by": "agent",
            "agent_id": current_user.id
        }),
        "agent"
    )

    return {
        "status": "ended",
        "session_id": request.session_id,
        "message": "Handoff call ended successfully"
    }


class SendMeetingLinkRequest(BaseModel):
    session_id: str


@router.post("/send-meeting-link")
async def send_meeting_link(
    request: SendMeetingLinkRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Manually send/resend a meeting link to the customer.
    This allows agents to send the meeting link again if the customer didn't receive it.
    """
    logger.info(f"[MEETING LINK] Agent {current_user.id} sending meeting link for session {request.session_id}")

    # Get the session
    session = conversation_session_service.get_session(db, request.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Check if session belongs to agent's company
    if session.company_id != current_user.company_id:
        raise HTTPException(status_code=403, detail="Access denied")

    # Check if the session is from a supported channel
    supported_channels = ['whatsapp', 'telegram', 'instagram', 'messenger']
    if session.channel not in supported_channels:
        raise HTTPException(
            status_code=400,
            detail=f"Meeting links not supported for channel: {session.channel}. Supported: {', '.join(supported_channels)}"
        )

    # Get integration for the channel
    integration = integration_service.get_integration_by_type_and_company(
        db, session.channel, session.company_id
    )
    if not integration:
        raise HTTPException(
            status_code=400,
            detail=f"No {session.channel} integration configured for this company"
        )

    # Create or get LiveKit room
    agent_name = f"{current_user.first_name} {current_user.last_name}".strip() if current_user.first_name else current_user.email
    customer_name = session.contact.name if session.contact and session.contact.name else "Customer"

    try:
        call_room = livekit_service.create_call_room(
            session_id=request.session_id,
            user_identity=f"user_{request.session_id}",
            agent_identity=f"agent_{current_user.id}",
            user_name=customer_name,
            agent_name=agent_name
        )

        # Generate meeting link
        meeting_link = livekit_service.generate_meeting_link(
            room_name=call_room["room_name"],
            user_token=call_room["user_token"]
        )

        # Send meeting link to customer
        await messaging_service.send_meeting_link(
            channel=session.channel,
            recipient_id=session.conversation_id,
            meeting_link=meeting_link,
            agent_name=agent_name,
            integration=integration,
            db=db
        )

        logger.info(f"[MEETING LINK] Sent meeting link to customer via {session.channel}")

        return {
            "status": "sent",
            "session_id": request.session_id,
            "channel": session.channel,
            "meeting_link": meeting_link,
            "room_name": call_room["room_name"],
            "agent_token": call_room["agent_token"],
            "livekit_url": settings.LIVEKIT_URL
        }

    except Exception as e:
        logger.error(f"[MEETING LINK] Failed to send meeting link: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to send meeting link: {str(e)}")
