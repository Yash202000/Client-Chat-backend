from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_
from typing import List, Optional
from datetime import datetime
from app.models.entity_note import EntityNote, NoteType
from app.models.contact import Contact
from app.models.lead import Lead
from app.schemas.entity_note import EntityNoteCreate, EntityNoteUpdate


def get_note(db: Session, note_id: int, company_id: int) -> Optional[EntityNote]:
    """Get a single note by ID"""
    return db.query(EntityNote).options(
        joinedload(EntityNote.creator)
    ).filter(
        EntityNote.id == note_id,
        EntityNote.company_id == company_id
    ).first()


def get_notes_for_contact(
    db: Session,
    contact_id: int,
    company_id: int,
    note_type: Optional[NoteType] = None,
    skip: int = 0,
    limit: int = 100
) -> List[EntityNote]:
    """Get all notes for a specific contact"""
    query = db.query(EntityNote).options(
        joinedload(EntityNote.creator)
    ).filter(
        EntityNote.contact_id == contact_id,
        EntityNote.company_id == company_id
    )

    if note_type:
        query = query.filter(EntityNote.note_type == note_type)

    return query.order_by(EntityNote.created_at.desc()).offset(skip).limit(limit).all()


def get_notes_for_lead(
    db: Session,
    lead_id: int,
    company_id: int,
    note_type: Optional[NoteType] = None,
    skip: int = 0,
    limit: int = 100
) -> List[EntityNote]:
    """Get all notes for a specific lead"""
    query = db.query(EntityNote).options(
        joinedload(EntityNote.creator)
    ).filter(
        EntityNote.lead_id == lead_id,
        EntityNote.company_id == company_id
    )

    if note_type:
        query = query.filter(EntityNote.note_type == note_type)

    return query.order_by(EntityNote.created_at.desc()).offset(skip).limit(limit).all()


def count_notes_for_contact(db: Session, contact_id: int, company_id: int) -> int:
    """Count total notes for a contact"""
    return db.query(EntityNote).filter(
        EntityNote.contact_id == contact_id,
        EntityNote.company_id == company_id
    ).count()


def count_notes_for_lead(db: Session, lead_id: int, company_id: int) -> int:
    """Count total notes for a lead"""
    return db.query(EntityNote).filter(
        EntityNote.lead_id == lead_id,
        EntityNote.company_id == company_id
    ).count()


def create_note(
    db: Session,
    note_data: EntityNoteCreate,
    company_id: int,
    user_id: int
) -> EntityNote:
    """Create a new note for a contact or lead"""
    # Validate that either contact_id or lead_id is provided, but not both
    if not note_data.contact_id and not note_data.lead_id:
        raise ValueError("Either contact_id or lead_id must be provided")
    if note_data.contact_id and note_data.lead_id:
        raise ValueError("Cannot specify both contact_id and lead_id")

    # Verify the contact/lead belongs to the company
    if note_data.contact_id:
        contact = db.query(Contact).filter(
            Contact.id == note_data.contact_id,
            Contact.company_id == company_id
        ).first()
        if not contact:
            raise ValueError("Contact not found or does not belong to this company")

    if note_data.lead_id:
        lead = db.query(Lead).filter(
            Lead.id == note_data.lead_id,
            Lead.company_id == company_id
        ).first()
        if not lead:
            raise ValueError("Lead not found or does not belong to this company")

    db_note = EntityNote(
        company_id=company_id,
        created_by=user_id,
        contact_id=note_data.contact_id,
        lead_id=note_data.lead_id,
        note_type=note_data.note_type,
        title=note_data.title,
        content=note_data.content,
        activity_date=note_data.activity_date,
        duration_minutes=note_data.duration_minutes,
        participants=note_data.participants,
        outcome=note_data.outcome,
    )

    db.add(db_note)
    db.commit()
    db.refresh(db_note)

    # Load creator relationship
    db.refresh(db_note, ['creator'])
    return db_note


def update_note(
    db: Session,
    note_id: int,
    note_data: EntityNoteUpdate,
    company_id: int,
    user_id: int
) -> Optional[EntityNote]:
    """Update an existing note"""
    db_note = get_note(db, note_id, company_id)

    if not db_note:
        return None

    # Update only provided fields
    update_data = note_data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_note, key, value)

    db_note.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(db_note)
    return db_note


def delete_note(db: Session, note_id: int, company_id: int) -> bool:
    """Delete a note"""
    db_note = get_note(db, note_id, company_id)

    if not db_note:
        return False

    db.delete(db_note)
    db.commit()
    return True
