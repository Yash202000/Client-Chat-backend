from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel

from app.core.dependencies import get_db, get_current_active_user, get_current_company
from app.services import chat_service, agent_service, conversation_session_service
from app.schemas import chat_message as schemas_chat_message, session as schemas_session, conversation_session as schemas_conversation_session
from app.models import user as models_user

router = APIRouter()

class NoteCreate(BaseModel):
    message: str

class StatusUpdate(BaseModel):
    status: str

class AssigneeUpdate(BaseModel):
    user_id: int

class FeedbackUpdate(BaseModel):
    feedback_rating: int
    feedback_notes: Optional[str] = None

@router.get("/sessions/counts")
def get_session_counts(db: Session = Depends(get_db), current_user: models_user.User = Depends(get_current_active_user)):
    """
    Get counts of sessions by status for the company.
    Returns: { "open": count, "resolved": count, "all": count }
    """
    all_sessions = chat_service.get_sessions_with_details(db, company_id=current_user.company_id)

    open_count = sum(1 for s in all_sessions if s.status not in ['resolved', 'archived'])
    resolved_count = sum(1 for s in all_sessions if s.status in ['resolved', 'archived'])

    return {
        "open": open_count,
        "resolved": resolved_count,
        "all": len(all_sessions)
    }

@router.get("/sessions", response_model=List[schemas_session.Session])
def get_all_sessions(
    status_filter: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Get sessions for the company, enriched with contact and channel info.

    Query Parameters:
    - status_filter: Filter by status category ('open', 'resolved', or None for all)
      - 'open' returns: active, inactive, assigned, pending
      - 'resolved' returns: resolved, archived
      - None returns: all sessions
    """
    sessions_from_db = chat_service.get_sessions_with_details(db, company_id=current_user.company_id)

    # Apply status filter
    if status_filter == 'open':
        sessions_from_db = [s for s in sessions_from_db if s.status not in ['resolved', 'archived']]
    elif status_filter == 'resolved':
        sessions_from_db = [s for s in sessions_from_db if s.status in ['resolved', 'archived']]

    sessions = []
    for s in sessions_from_db:
        first_message = chat_service.get_first_message_for_session(db, s.conversation_id, current_user.company_id)
        contact_info = chat_service.get_contact_for_session(db, s.conversation_id, current_user.company_id)

        sessions.append(schemas_session.Session(
            session_id=s.conversation_id,
            status=s.status,
            assignee_id=s.agent_id,
            last_message_timestamp=s.updated_at.isoformat(),
            first_message_content=first_message.message if first_message else "",
            channel=s.channel,
            contact_name=contact_info.name if contact_info else "Unknown",
            contact_phone=contact_info.phone_number if contact_info else None
        ))
    return sessions

@router.get("/{agent_id}/sessions", response_model=List[schemas_session.Session], deprecated=True)
def get_sessions_by_agent(agent_id: int, db: Session = Depends(get_db), current_user: models_user.User = Depends(get_current_active_user)):
    # This endpoint is deprecated in favor of the company-wide /sessions endpoint
    sessions_from_db = chat_service.get_sessions_with_details(db, agent_id=agent_id, company_id=current_user.company_id)
    
    sessions = []
    for s in sessions_from_db:
        first_message = chat_service.get_first_message_for_session(db, s.conversation_id, current_user.company_id)
        sessions.append(schemas_session.Session(
            session_id=s.conversation_id,
            status=s.status,
            assignee_id=s.agent_id,
            last_message_timestamp=s.updated_at.isoformat(),
            first_message_content=first_message.message if first_message else ""
        ))
    return sessions


@router.get("/{agent_id}/sessions/{session_id}", response_model=schemas_session.Session)
def get_session_detial_by_agent_id_session_id(agent_id: int, session_id: int, db: Session = Depends(get_db), current_user: models_user.User = Depends(get_current_active_user)):
    # This endpoint is deprecated in favor of the company-wide /sessions endpoint
    sessions_from_db = chat_service.get_session_details(db, agent_id=agent_id, broadcast_session_id=session_id, company_id=current_user.company_id)
    return schemas_session.Session(
            session_id=sessions_from_db.conversation_id,
            status=sessions_from_db.status,
            assignee_id=sessions_from_db.agent_id,
            last_message_timestamp=sessions_from_db.updated_at.isoformat(),
            first_message_content= ""
        )

@router.get("/{agent_id}/{session_id}", response_model=List[schemas_chat_message.ChatMessage])
def get_messages(agent_id: int, session_id: str, db: Session = Depends(get_db), current_user: models_user.User = Depends(get_current_active_user)):
    return chat_service.get_chat_messages(db, agent_id=agent_id, session_id=session_id, company_id=current_user.company_id)

@router.post("/{agent_id}/{session_id}/notes", response_model=schemas_chat_message.ChatMessage)
def create_note(
    agent_id: int,
    session_id: str,
    note: NoteCreate,
    db: Session = Depends(get_db),

    current_user: models_user.User = Depends(get_current_active_user)
):
    # We can consider adding author_id to notes in the future
    # For now, sender will be 'agent'
    message_schema = schemas_chat_message.ChatMessageCreate(message=note.message, message_type="note")
    return chat_service.create_chat_message(
        db=db,
        message=message_schema,
        agent_id=agent_id,
        session_id=session_id,
        company_id=current_user.company_id,
        sender="agent" 
    )

@router.put("/{session_id}/status")
async def update_status(
    session_id: str,
    status_update: StatusUpdate,
    db: Session = Depends(get_db),

    current_user: models_user.User = Depends(get_current_active_user)
):
    success = await chat_service.update_conversation_status(db, session_id=session_id, status=status_update.status, company_id=current_user.company_id)
    if not success:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"message": "Status updated successfully"}

@router.put("/{session_id}/assignee")
async def update_assignee(
    session_id: str,
    assignee_update: AssigneeUpdate,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    success = await chat_service.update_conversation_assignee(db, session_id=session_id, user_id=assignee_update.user_id, company_id=current_user.company_id)
    if not success:
        raise HTTPException(status_code=404, detail="Conversation not found or assignee update failed")
    return {"message": "Assignee updated successfully"}

class AIToggleUpdate(BaseModel):
    is_ai_enabled: bool

@router.put("/{session_id}/toggle-ai", response_model=schemas_conversation_session.ConversationSession)
def toggle_ai(
    session_id: str,
    update: AIToggleUpdate,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Toggles the AI automated response for a specific conversation session.
    """
    session = conversation_session_service.toggle_ai_for_session(
        db, 
        conversation_id=session_id, 
        company_id=current_user.company_id, 
        is_enabled=update.is_ai_enabled
    )
    if not session:
        raise HTTPException(status_code=404, detail="Conversation session not found")
    return session


@router.put("/{session_id}/feedback")
def update_feedback(
    session_id: str,
    feedback_update: FeedbackUpdate,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    success = chat_service.update_conversation_feedback(
        db=db,
        session_id=session_id,
        feedback_rating=feedback_update.feedback_rating,
        feedback_notes=feedback_update.feedback_notes,
        company_id=current_user.company_id
    )
    if not success:
        raise HTTPException(status_code=404, detail="Conversation not found or feedback update failed")
    return {"message": "Feedback submitted successfully"}