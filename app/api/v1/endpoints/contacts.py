from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.core.dependencies import get_db
from app.services import contact_service
from app.schemas import contact as schemas_contact

router = APIRouter()

@router.get("/", response_model=List[schemas_contact.Contact])
def read_contacts(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    x_company_id: int = Header(...)
):
    contacts = contact_service.get_contacts(db, company_id=x_company_id, skip=skip, limit=limit)
    return contacts

@router.get("/{contact_id}", response_model=schemas_contact.Contact)
def read_contact(
    contact_id: int,
    db: Session = Depends(get_db),
    x_company_id: int = Header(...)
):
    db_contact = contact_service.get_contact(db, contact_id=contact_id, company_id=x_company_id)
    if db_contact is None:
        raise HTTPException(status_code=404, detail="Contact not found")
    return db_contact

@router.put("/{contact_id}", response_model=schemas_contact.Contact)
def update_contact(
    contact_id: int,
    contact: schemas_contact.ContactUpdate,
    db: Session = Depends(get_db),
    x_company_id: int = Header(...)
):
    return contact_service.update_contact(db=db, contact_id=contact_id, contact=contact, company_id=x_company_id)

@router.get("/by_session/{session_id}", response_model=schemas_contact.Contact)
def get_contact_by_session(
    session_id: str,
    db: Session = Depends(get_db),
    x_company_id: int = Header(...)
):
    session = db.query(models_conversation_session.ConversationSession).filter(
        models_conversation_session.ConversationSession.conversation_id == session_id,
        models_conversation_session.ConversationSession.company_id == x_company_id
    ).first()
    if not session or not session.contact:
        raise HTTPException(status_code=404, detail="Contact for this session not found")
    return session.contact
