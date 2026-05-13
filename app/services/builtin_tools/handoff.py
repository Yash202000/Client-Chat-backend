"""
Handoff builtin tool implementation.
Handles transferring conversations to human agents.
"""
import traceback
from sqlalchemy.orm import Session
from app.models.agent import Agent
from app.services import agent_assignment_service, conversation_session_service


async def execute_handoff_tool(db: Session, session_id: str, parameters: dict):
    """
    Executes the built-in handoff tool to transfer conversation to a human agent.

    Args:
        db: Database session
        session_id: Conversation session ID
        parameters: Tool parameters (reason, summary, priority, pool)

    Returns:
        Dictionary with handoff result
    """
    reason = parameters.get("reason", "customer_request")
    summary = parameters.get("summary", "")
    priority = parameters.get("priority", "normal")

    # Get the session to find the agent
    session = conversation_session_service.get_session(db, session_id)
    if not session or not session.agent_id:
        team_name = "Support"  # Default fallback
    else:
        # Get the agent to find the configured handoff team
        agent = db.query(Agent).filter(Agent.id == session.agent_id).first()
        if agent and agent.handoff_team_id and agent.handoff_team:
            team_name = agent.handoff_team.name
        else:
            # Use parameter if provided, otherwise default to "Support"
            team_name = parameters.get("pool", "Support")


    try:
        # Request handoff via assignment service
        handoff_result = await agent_assignment_service.request_handoff(
            db=db,
            session_id=session_id,
            reason=reason,
            team_name=team_name,
            priority=priority
        )

        # Add summary to context
        handoff_result["summary"] = summary

        return {"result": handoff_result}

    except Exception as e:
        return {
            "error": "An error occurred while processing handoff request.",
            "details": str(e),
            "traceback": traceback.format_exc()
        }
