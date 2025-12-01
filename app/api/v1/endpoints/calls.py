
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.dependencies import get_db, get_current_user
from app.core.config import settings
from app.models.user import User
from app.services.connection_manager import manager
from app.services import agent_assignment_service
from livekit import api
import json

from app.schemas.call import StartCallRequest
from pydantic import BaseModel

router = APIRouter()

class AcceptCallRequest(BaseModel):
    session_id: str
    room_name: str
    livekit_url: str
    user_token: str

class RejectCallRequest(BaseModel):
    session_id: str
    reason: str = "Agent declined"

@router.post("/start")
def start_call(request: StartCallRequest, db: Session = Depends(get_db)):
    # For now, we just return a success message.
    # In a real implementation, you might create a record of the call in the database.
    return {"message": f"Call started for session {request.session_id}"}

@router.get("/token")
def get_join_token(session_id: str, user_id: str, db: Session = Depends(get_db)):
    if not settings.LIVEKIT_URL or not settings.LIVEKIT_API_KEY or not settings.LIVEKIT_API_SECRET:
        raise HTTPException(status_code=500, detail="LiveKit is not configured.")

    token = api.AccessToken(
        settings.LIVEKIT_API_KEY,
        settings.LIVEKIT_API_SECRET
    ).with_identity(user_id).with_name(user_id).with_grants(
        api.VideoGrants(room_join=True, room=session_id)
    )

    return {"token": token.to_jwt()}

@router.post("/accept")
async def accept_call(
    request: AcceptCallRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Agent accepts an incoming call. Assigns the session to the agent and notifies the customer.
    """
    try:
        # Get the session
        from app.services import conversation_session_service
        session = conversation_session_service.get_session(db, request.session_id)

        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        # Assign the session to the agent
        team_name = session.assigned_pool or "Support"
        await agent_assignment_service.assign_session_to_agent(
            db=db,
            session_id=request.session_id,
            agent_user_id=current_user.id,
            company_id=session.company_id,
            reason="call_accepted",
            team_name=team_name
        )

        # Broadcast call accepted message to the customer
        call_accepted_message = {
            "type": "call_accepted",
            "session_id": request.session_id,
            "agent_name": f"{current_user.first_name} {current_user.last_name}".strip() or current_user.email,
            "room_name": request.room_name,
            "livekit_url": request.livekit_url,
            "user_token": request.user_token
        }

        # Broadcast to the session (customer's widget)
        await manager.broadcast_to_session(request.session_id, json.dumps(call_accepted_message), "agent")

        return {
            "status": "accepted",
            "session_id": request.session_id,
            "room_name": request.room_name
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to accept call: {str(e)}")

@router.post("/reject")
async def reject_call(
    request: RejectCallRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Agent rejects an incoming call. Notifies the customer and resets the session state.
    """
    try:
        # Get the session
        from app.services import conversation_session_service
        from app.schemas.conversation_session import ConversationSessionUpdate
        from datetime import datetime

        session = conversation_session_service.get_session(db, request.session_id)

        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        # Update session to reset handoff state
        session_update = ConversationSessionUpdate(
            waiting_for_agent=False,
            status='active',
            is_ai_enabled=True  # Re-enable AI
        )

        conversation_session_service.update_session(db, request.session_id, session_update)

        # Broadcast call rejected message to the customer
        call_rejected_message = {
            "type": "call_rejected",
            "session_id": request.session_id,
            "reason": request.reason,
            "message": "The agent is currently unavailable. You can continue chatting with our AI assistant."
        }

        # Broadcast to the session (customer's widget)
        await manager.broadcast_to_session(request.session_id, json.dumps(call_rejected_message), "agent")

        return {
            "status": "rejected",
            "session_id": request.session_id
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to reject call: {str(e)}")
