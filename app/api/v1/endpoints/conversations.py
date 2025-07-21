from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel

from app.core.dependencies import get_db, get_current_active_user, get_current_company
from app.services import chat_service, agent_service
from app.schemas import chat_message as schemas_chat_message, session as schemas_session
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

@router.get("/{agent_id}/sessions", response_model=List[schemas_session.Session])
def get_sessions(agent_id: int, db: Session = Depends(get_db), current_company_id: int = Depends(get_current_company), current_user: models_user.User = Depends(get_current_active_user)):
    sessions_from_db = chat_service.get_sessions_with_details(db, agent_id=agent_id, company_id=current_company_id)
    
    sessions = []
    for s in sessions_from_db:
        first_message = chat_service.get_first_message_for_session(db, s.session_id, current_company_id)
        sessions.append(schemas_session.Session(
            session_id=s.session_id,
            status=s.status,
            assignee_id=s.assignee_id,
            last_message_timestamp=s.timestamp.isoformat(),
            first_message_content=first_message.message if first_message else ""
        ))
    return sessions

@router.get("/{agent_id}/{session_id}", response_model=List[schemas_chat_message.ChatMessage])
def get_messages(agent_id: int, session_id: str, db: Session = Depends(get_db), current_company_id: int = Depends(get_current_company), current_user: models_user.User = Depends(get_current_active_user)):
    return chat_service.get_chat_messages(db, agent_id=agent_id, session_id=session_id, company_id=current_company_id)

@router.post("/{agent_id}/{session_id}/notes", response_model=schemas_chat_message.ChatMessage)
def create_note(
    agent_id: int,
    session_id: str,
    note: NoteCreate,
    db: Session = Depends(get_db),
    current_company_id: int = Depends(get_current_company),
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
        company_id=current_company_id,
        sender="agent" 
    )

@router.put("/{session_id}/status")
def update_status(
    session_id: str,
    status_update: StatusUpdate,
    db: Session = Depends(get_db),
    current_company_id: int = Depends(get_current_company),
    current_user: models_user.User = Depends(get_current_active_user)
):
    success = chat_service.update_conversation_status(db, session_id=session_id, status=status_update.status, company_id=current_company_id)
    if not success:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"message": "Status updated successfully"}

@router.put("/{session_id}/assignee")
def update_assignee(
    session_id: str,
    assignee_update: AssigneeUpdate,
    db: Session = Depends(get_db),
    current_company_id: int = Depends(get_current_company),
    current_user: models_user.User = Depends(get_current_active_user)
):
    success = chat_service.update_conversation_assignee(db, session_id=session_id, user_id=assignee_update.user_id, company_id=current_company_id)
    if not success:
        raise HTTPException(status_code=404, detail="Conversation not found or assignee update failed")
    return {"message": "Assignee updated successfully"}

@router.put("/{session_id}/feedback")
def update_feedback(
    session_id: str,
    feedback_update: FeedbackUpdate,
    db: Session = Depends(get_db),
    current_company_id: int = Depends(get_current_company),
    current_user: models_user.User = Depends(get_current_active_user)
):
    success = chat_service.update_conversation_feedback(
        db=db,
        session_id=session_id,
        feedback_rating=feedback_update.feedback_rating,
        feedback_notes=feedback_update.feedback_notes,
        company_id=current_company_id
    )
    if not success:
        raise HTTPException(status_code=404, detail="Conversation not found or feedback update failed")
    return {"message": "Feedback submitted successfully"}