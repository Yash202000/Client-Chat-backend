from sqlalchemy.orm import Session
from app.models import contact as models_contact, chat_message as models_chat_message
from app.schemas import contact as schemas_contact

def get_contact(db: Session, contact_id: int, company_id: int):
    return db.query(models_contact.Contact).filter(models_contact.Contact.id == contact_id, models_contact.Contact.company_id == company_id).first()

def get_contacts(db: Session, company_id: int, skip: int = 0, limit: int = 100):
    return db.query(models_contact.Contact).filter(models_contact.Contact.company_id == company_id).offset(skip).limit(limit).all()

def get_or_create_contact_by_session(db: Session, session_id: str, company_id: int, contact_info: schemas_contact.ContactCreate = None):
    # Check if a message in this session already has a contact
    first_message = db.query(models_chat_message.ChatMessage).filter(
        models_chat_message.ChatMessage.session_id == session_id,
        models_chat_message.ChatMessage.contact_id != None
    ).first()

    if first_message and first_message.contact:
        return first_message.contact

    # If no contact is associated, create a new one
    if contact_info and contact_info.email:
        # Check if a contact with this email already exists
        existing_contact = db.query(models_contact.Contact).filter(
            models_contact.Contact.email == contact_info.email,
            models_contact.Contact.company_id == company_id
        ).first()
        if existing_contact:
            return existing_contact

    # Create a new contact if none exists
    new_contact = create_contact(db, contact_info if contact_info else schemas_contact.ContactCreate(), company_id)
    return new_contact

def create_contact(db: Session, contact: schemas_contact.ContactCreate, company_id: int):
    db_contact = models_contact.Contact(
        **contact.dict(),
        company_id=company_id
    )
    db.add(db_contact)
    db.commit()
    db.refresh(db_contact)
    return db_contact

def update_contact(db: Session, contact_id: int, contact: schemas_contact.ContactUpdate, company_id: int):
    db_contact = get_contact(db, contact_id, company_id)
    if db_contact:
        update_data = contact.dict(exclude_unset=True)
        for key, value in update_data.items():
            setattr(db_contact, key, value)
        db.commit()
        db.refresh(db_contact)
    return db_contact

def link_session_to_contact(db: Session, session_id: str, contact_id: int):
    db.query(models_chat_message.ChatMessage).filter(
        models_chat_message.ChatMessage.session_id == session_id
    ).update({"contact_id": contact_id})
    db.commit()
    return True
