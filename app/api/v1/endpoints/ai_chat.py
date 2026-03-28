
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from pydantic import BaseModel
from typing import Optional
import datetime

from app.core.dependencies import get_db, get_current_active_user
from app.models import user as models_user
from app.models import conversation_session as models_session
from app.models import chat_message as models_message
from app.services import ai_chat_service
from app.schemas import ai_chat as schemas_ai_chat, chat_message as schemas_chat_message

router = APIRouter()


class SessionSummary(BaseModel):
    conversation_id: str
    agent_id: Optional[int]
    agent_name: Optional[str]
    last_message: Optional[str]
    last_message_at: Optional[datetime.datetime]
    message_count: int
    created_at: datetime.datetime


class MessageOut(BaseModel):
    id: int
    message: str
    sender: str
    timestamp: Optional[datetime.datetime]

    class Config:
        from_attributes = True


@router.post("/", response_model=schemas_chat_message.ChatMessage)
async def post_ai_chat(
    chat_request: schemas_ai_chat.AIChatRequest,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    return await ai_chat_service.handle_ai_chat(
        db=db,
        chat_request=chat_request,
        company_id=current_user.company_id,
        user_id=current_user.id
    )


@router.get("/sessions", response_model=List[SessionSummary])
def get_ai_chat_sessions(
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """List all ai_chat sessions for the current user's company, newest first."""
    sessions = (
        db.query(models_session.ConversationSession)
        .filter(
            models_session.ConversationSession.company_id == current_user.company_id,
            models_session.ConversationSession.channel == "ai_chat"
        )
        .order_by(models_session.ConversationSession.updated_at.desc())
        .limit(50)
        .all()
    )

    result = []
    for s in sessions:
        msgs = (
            db.query(models_message.ChatMessage)
            .filter(models_message.ChatMessage.session_id == s.id)
            .order_by(models_message.ChatMessage.timestamp.desc())
            .limit(1)
            .all()
        )
        last_msg = msgs[0] if msgs else None
        total = db.query(models_message.ChatMessage).filter(models_message.ChatMessage.session_id == s.id).count()
        agent_name = s.agent.name if s.agent else None
        result.append(SessionSummary(
            conversation_id=s.conversation_id,
            agent_id=s.agent_id,
            agent_name=agent_name,
            last_message=last_msg.message[:80] if last_msg else None,
            last_message_at=last_msg.timestamp if last_msg else None,
            message_count=total,
            created_at=s.created_at,
        ))
    return result


@router.get("/sessions/{conversation_id}/messages", response_model=List[MessageOut])
def get_session_messages(
    conversation_id: str,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """Fetch all messages for a given ai_chat session."""
    session = (
        db.query(models_session.ConversationSession)
        .filter(
            models_session.ConversationSession.conversation_id == conversation_id,
            models_session.ConversationSession.company_id == current_user.company_id,
        )
        .first()
    )
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    messages = (
        db.query(models_message.ChatMessage)
        .filter(models_message.ChatMessage.session_id == session.id)
        .order_by(models_message.ChatMessage.timestamp.asc())
        .all()
    )
    return messages
