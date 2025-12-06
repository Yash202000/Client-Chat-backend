from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional

from app.core.dependencies import get_db, get_current_active_user
from app.services import entity_note_service
from app.schemas.entity_note import (
    EntityNoteCreate,
    EntityNoteUpdate,
    EntityNoteResponse,
    EntityNoteList,
    NoteType,
)
from app.models import user as models_user

router = APIRouter()


@router.post("/", response_model=EntityNoteResponse)
def create_note(
    note: EntityNoteCreate,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Create a new note for a contact or lead.
    Either contact_id or lead_id must be provided, but not both.
    """
    try:
        db_note = entity_note_service.create_note(
            db=db,
            note_data=note,
            company_id=current_user.company_id,
            user_id=current_user.id
        )
        # Build response with creator email
        return EntityNoteResponse(
            id=db_note.id,
            company_id=db_note.company_id,
            contact_id=db_note.contact_id,
            lead_id=db_note.lead_id,
            note_type=db_note.note_type,
            title=db_note.title,
            content=db_note.content,
            activity_date=db_note.activity_date,
            duration_minutes=db_note.duration_minutes,
            participants=db_note.participants,
            outcome=db_note.outcome,
            created_by=db_note.created_by,
            creator_email=db_note.creator.email if db_note.creator else None,
            created_at=db_note.created_at,
            updated_at=db_note.updated_at,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/contact/{contact_id}", response_model=EntityNoteList)
def get_notes_for_contact(
    contact_id: int,
    note_type: Optional[NoteType] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Get all notes for a specific contact
    """
    from app.models.entity_note import NoteType as NoteTypeModel

    notes = entity_note_service.get_notes_for_contact(
        db=db,
        contact_id=contact_id,
        company_id=current_user.company_id,
        note_type=NoteTypeModel(note_type.value) if note_type else None,
        skip=skip,
        limit=limit
    )
    total = entity_note_service.count_notes_for_contact(
        db=db,
        contact_id=contact_id,
        company_id=current_user.company_id
    )

    return EntityNoteList(
        notes=[
            EntityNoteResponse(
                id=n.id,
                company_id=n.company_id,
                contact_id=n.contact_id,
                lead_id=n.lead_id,
                note_type=n.note_type,
                title=n.title,
                content=n.content,
                activity_date=n.activity_date,
                duration_minutes=n.duration_minutes,
                participants=n.participants,
                outcome=n.outcome,
                created_by=n.created_by,
                creator_email=n.creator.email if n.creator else None,
                created_at=n.created_at,
                updated_at=n.updated_at,
            )
            for n in notes
        ],
        total=total
    )


@router.get("/lead/{lead_id}", response_model=EntityNoteList)
def get_notes_for_lead(
    lead_id: int,
    note_type: Optional[NoteType] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Get all notes for a specific lead
    """
    from app.models.entity_note import NoteType as NoteTypeModel

    notes = entity_note_service.get_notes_for_lead(
        db=db,
        lead_id=lead_id,
        company_id=current_user.company_id,
        note_type=NoteTypeModel(note_type.value) if note_type else None,
        skip=skip,
        limit=limit
    )
    total = entity_note_service.count_notes_for_lead(
        db=db,
        lead_id=lead_id,
        company_id=current_user.company_id
    )

    return EntityNoteList(
        notes=[
            EntityNoteResponse(
                id=n.id,
                company_id=n.company_id,
                contact_id=n.contact_id,
                lead_id=n.lead_id,
                note_type=n.note_type,
                title=n.title,
                content=n.content,
                activity_date=n.activity_date,
                duration_minutes=n.duration_minutes,
                participants=n.participants,
                outcome=n.outcome,
                created_by=n.created_by,
                creator_email=n.creator.email if n.creator else None,
                created_at=n.created_at,
                updated_at=n.updated_at,
            )
            for n in notes
        ],
        total=total
    )


@router.get("/{note_id}", response_model=EntityNoteResponse)
def get_note(
    note_id: int,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Get a specific note by ID
    """
    note = entity_note_service.get_note(
        db=db,
        note_id=note_id,
        company_id=current_user.company_id
    )
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")

    return EntityNoteResponse(
        id=note.id,
        company_id=note.company_id,
        contact_id=note.contact_id,
        lead_id=note.lead_id,
        note_type=note.note_type,
        title=note.title,
        content=note.content,
        activity_date=note.activity_date,
        duration_minutes=note.duration_minutes,
        participants=note.participants,
        outcome=note.outcome,
        created_by=note.created_by,
        creator_email=note.creator.email if note.creator else None,
        created_at=note.created_at,
        updated_at=note.updated_at,
    )


@router.put("/{note_id}", response_model=EntityNoteResponse)
def update_note(
    note_id: int,
    note: EntityNoteUpdate,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Update an existing note
    """
    updated_note = entity_note_service.update_note(
        db=db,
        note_id=note_id,
        note_data=note,
        company_id=current_user.company_id,
        user_id=current_user.id
    )
    if not updated_note:
        raise HTTPException(status_code=404, detail="Note not found")

    return EntityNoteResponse(
        id=updated_note.id,
        company_id=updated_note.company_id,
        contact_id=updated_note.contact_id,
        lead_id=updated_note.lead_id,
        note_type=updated_note.note_type,
        title=updated_note.title,
        content=updated_note.content,
        activity_date=updated_note.activity_date,
        duration_minutes=updated_note.duration_minutes,
        participants=updated_note.participants,
        outcome=updated_note.outcome,
        created_by=updated_note.created_by,
        creator_email=updated_note.creator.email if updated_note.creator else None,
        created_at=updated_note.created_at,
        updated_at=updated_note.updated_at,
    )


@router.delete("/{note_id}")
def delete_note(
    note_id: int,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Delete a note
    """
    success = entity_note_service.delete_note(
        db=db,
        note_id=note_id,
        company_id=current_user.company_id
    )
    if not success:
        raise HTTPException(status_code=404, detail="Note not found")
    return {"success": True}
