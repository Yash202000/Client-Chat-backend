from sqlalchemy.orm import Session
from sqlalchemy import and_
from typing import List, Optional
from app.models import contact as models_contact, chat_message as models_chat_message
from app.models.tag import contact_tags, Tag
from app.schemas import contact as schemas_contact

def get_contact(db: Session, contact_id: int, company_id: int):
    return db.query(models_contact.Contact).filter(models_contact.Contact.id == contact_id, models_contact.Contact.company_id == company_id).first()

def get_contacts(db: Session, company_id: int, skip: int = 0, limit: int = 100, tag_ids: Optional[List[int]] = None):
    query = db.query(models_contact.Contact).filter(models_contact.Contact.company_id == company_id)

    # Filter by tags if provided
    if tag_ids:
        # Use subquery to avoid DISTINCT issues with JSON columns
        from sqlalchemy import exists, select
        subq = select(contact_tags.c.contact_id).where(
            and_(
                contact_tags.c.contact_id == models_contact.Contact.id,
                contact_tags.c.tag_id.in_(tag_ids)
            )
        ).exists()
        query = query.filter(subq)

    return query.offset(skip).limit(limit).all()

def create_contact(db: Session, contact: schemas_contact.ContactCreate, company_id: int):
    db_contact = models_contact.Contact(
        **contact.model_dump(),
        company_id=company_id
    )
    db.add(db_contact)
    db.commit()
    db.refresh(db_contact)
    return db_contact

def update_contact(db: Session, contact_id: int, contact: schemas_contact.ContactUpdate, company_id: int):
    db_contact = get_contact(db, contact_id, company_id)
    if db_contact:
        update_data = contact.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(db_contact, key, value)
        db.commit()
        db.refresh(db_contact)
    return db_contact

def get_or_create_contact_for_channel(db: Session, company_id: int, channel: str, channel_identifier: str, name: str = None):
    """
    Finds a contact by a channel-specific identifier, or creates one if it doesn't exist.
    This is the central function for handling contacts from different platforms.

    Args:
        db: The database session.
        company_id: The ID of the company.
        channel: The name of the channel (e.g., 'whatsapp', 'messenger').
        channel_identifier: The unique ID for the user on that channel (e.g., phone number, PSID).
        name: The contact's name, if available.

    Returns:
        The existing or newly created contact object.
    """
    # Use a consistent key for the custom attribute
    attribute_key = f"{channel}_id"

    # Query for an existing contact using a JSON query that works across DBs
    contact = db.query(models_contact.Contact).filter(
        models_contact.Contact.company_id == company_id,
        models_contact.Contact.custom_attributes[attribute_key].as_string() == channel_identifier
    ).first()

    if contact:
        return contact

    # If no contact is found, create a new one
    contact_details = {
        "custom_attributes": {attribute_key: channel_identifier},
        "company_id": company_id
    }
    if name:
        contact_details["name"] = name
    
    # For WhatsApp, the identifier is the phone number
    if channel == 'whatsapp':
        contact_details["phone_number"] = channel_identifier

    new_contact_schema = schemas_contact.ContactCreate(**contact_details)
    return create_contact(db, contact=new_contact_schema, company_id=company_id)

