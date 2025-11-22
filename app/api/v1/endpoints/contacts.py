from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.core.dependencies import get_db, get_current_active_user
from app.services import contact_service
from app.schemas import contact as schemas_contact
from app.models import conversation_session as models_conversation_session
from app.models import user as models_user

router = APIRouter()

@router.get("/", response_model=List[schemas_contact.Contact])
def read_contacts(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    contacts = contact_service.get_contacts(db, company_id=current_user.company_id, skip=skip, limit=limit)
    return contacts

@router.get("/{contact_id}", response_model=schemas_contact.Contact)
def read_contact(
    contact_id: int,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    db_contact = contact_service.get_contact(db, contact_id=contact_id, company_id=current_user.company_id)
    if db_contact is None:
        raise HTTPException(status_code=404, detail="Contact not found")
    return db_contact

@router.put("/{contact_id}", response_model=schemas_contact.Contact)
def update_contact(
    contact_id: int,
    contact: schemas_contact.ContactUpdate,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    return contact_service.update_contact(db=db, contact_id=contact_id, contact=contact, company_id=current_user.company_id)

@router.get("/by_session/{session_id}")
def get_contact_by_session(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Get contact for a session. Returns null if session has no contact (anonymous sessions).
    """
    session = db.query(models_conversation_session.ConversationSession).filter(
        models_conversation_session.ConversationSession.conversation_id == str(session_id),
        models_conversation_session.ConversationSession.company_id == current_user.company_id
    ).first()

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Return null if session has no contact (anonymous session)
    if not session.contact:
        return None

    return session.contact
