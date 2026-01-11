from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from typing import List, Optional
from app.models import contact as models_contact, chat_message as models_chat_message
from app.models.tag import contact_tags, Tag
from app.schemas import contact as schemas_contact


# Channel configuration for contact deduplication behavior
# is_phone_channel: True if channel_identifier is a phone number (enables phone_number matching)
CHANNEL_CONFIG = {
    'whatsapp': {'attribute_key': 'whatsapp_id', 'is_phone_channel': True},
    'twilio_voice': {'attribute_key': 'twilio_voice_id', 'is_phone_channel': True},
    'freeswitch': {'attribute_key': 'freeswitch_id', 'is_phone_channel': True},
    'telegram': {'attribute_key': 'telegram_id', 'is_phone_channel': False},
    'instagram': {'attribute_key': 'instagram_id', 'is_phone_channel': False},
    'messenger': {'attribute_key': 'messenger_id', 'is_phone_channel': False},
}

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


def _link_channel_to_contact(
    db: Session,
    contact: models_contact.Contact,
    attribute_key: str,
    channel_identifier: str,
    is_phone_channel: bool
) -> models_contact.Contact:
    """
    Links a channel to an existing contact by updating custom_attributes.
    Also updates phone_number if this is a phone-based channel and not already set.
    """
    needs_update = False

    # Initialize custom_attributes if None
    if contact.custom_attributes is None:
        contact.custom_attributes = {}

    # Add channel_id if not already set
    if contact.custom_attributes.get(attribute_key) != channel_identifier:
        # Create a new dict to trigger SQLAlchemy change detection for JSON columns
        new_attrs = dict(contact.custom_attributes)
        new_attrs[attribute_key] = channel_identifier
        contact.custom_attributes = new_attrs
        needs_update = True

    # Update phone_number if this is a phone channel and contact doesn't have one
    if is_phone_channel and not contact.phone_number and channel_identifier:
        contact.phone_number = channel_identifier
        needs_update = True

    if needs_update:
        db.commit()
        db.refresh(contact)

    return contact


def get_or_create_contact_for_channel(
    db: Session,
    company_id: int,
    channel: str,
    channel_identifier: str,
    name: str = None,
    email: str = None
):
    """
    Finds a contact using cascading lookup, or creates one if none exists.
    This is the central function for handling contacts from different platforms.

    Implements contact deduplication across channels by checking multiple identifiers
    in priority order:
    1. Channel-specific ID (e.g., custom_attributes['whatsapp_id'])
    2. Phone number (for phone-based channels like WhatsApp, Twilio Voice, FreeSWITCH)
    3. Email (if provided)

    If a match is found:
    - Returns the existing contact
    - Updates custom_attributes[{channel}_id] if not already set (links channel to contact)
    - Updates phone_number if it's a phone channel and phone was not set

    Args:
        db: The database session.
        company_id: The ID of the company.
        channel: The name of the channel (e.g., 'whatsapp', 'messenger', 'telegram').
        channel_identifier: The unique ID for the user on that channel (e.g., phone number, PSID).
        name: The contact's name, if available.
        email: The contact's email, if available (used for additional matching).

    Returns:
        The existing or newly created contact object.
    """
    # Get channel configuration (with fallback for unknown channels)
    config = CHANNEL_CONFIG.get(channel, {
        'attribute_key': f'{channel}_id',
        'is_phone_channel': False
    })
    attribute_key = config['attribute_key']
    is_phone_channel = config['is_phone_channel']

    # Build OR conditions for cascading lookup (single efficient query)
    lookup_conditions = [
        # Priority 1: Channel-specific ID in custom_attributes
        models_contact.Contact.custom_attributes[attribute_key].as_string() == channel_identifier
    ]

    # Priority 2: Phone number match (for phone-based channels)
    if is_phone_channel and channel_identifier:
        lookup_conditions.append(
            models_contact.Contact.phone_number == channel_identifier
        )

    # Priority 3: Email match (if provided)
    if email:
        lookup_conditions.append(
            models_contact.Contact.email == email
        )

    # Execute single query with OR conditions
    contact = db.query(models_contact.Contact).filter(
        models_contact.Contact.company_id == company_id,
        or_(*lookup_conditions)
    ).first()

    if contact:
        # Link this channel to existing contact if not already set
        return _link_channel_to_contact(db, contact, attribute_key, channel_identifier, is_phone_channel)

    # No match found - create new contact
    contact_details = {
        "custom_attributes": {attribute_key: channel_identifier},
        "company_id": company_id
    }
    if name:
        contact_details["name"] = name
    if email:
        contact_details["email"] = email
    # For phone-based channels, set phone_number
    if is_phone_channel and channel_identifier:
        contact_details["phone_number"] = channel_identifier

    new_contact_schema = schemas_contact.ContactCreate(**contact_details)
    return create_contact(db, contact=new_contact_schema, company_id=company_id)

