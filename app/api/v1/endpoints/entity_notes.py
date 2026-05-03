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
from app.models.entity_note import NoteType as NoteTypeModel

router = APIRouter()


def _to_response(n) -> EntityNoteResponse:
    return EntityNoteResponse(
        id=n.id,
        company_id=n.company_id,
        contact_id=n.contact_id,
        lead_id=n.lead_id,
        deal_id=n.deal_id,
        account_id=n.account_id,
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


def _to_list(notes, total: int) -> EntityNoteList:
    return EntityNoteList(notes=[_to_response(n) for n in notes], total=total)


@router.post("/", response_model=EntityNoteResponse)
def create_note(
    note: EntityNoteCreate,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """Create a note for a contact, lead, deal, or account."""
    try:
        db_note = entity_note_service.create_note(
            db=db, note_data=note,
            company_id=current_user.company_id, user_id=current_user.id
        )
        return _to_response(db_note)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/contact/{contact_id}", response_model=EntityNoteList)
def get_notes_for_contact(
    contact_id: int,
    note_type: Optional[NoteType] = None,
    skip: int = 0, limit: int = 100,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    notes = entity_note_service.get_notes_for_contact(
        db=db, contact_id=contact_id, company_id=current_user.company_id,
        note_type=NoteTypeModel(note_type.value) if note_type else None,
        skip=skip, limit=limit
    )
    total = entity_note_service.count_notes_for_contact(db=db, contact_id=contact_id, company_id=current_user.company_id)
    return _to_list(notes, total)


@router.get("/lead/{lead_id}", response_model=EntityNoteList)
def get_notes_for_lead(
    lead_id: int,
    note_type: Optional[NoteType] = None,
    skip: int = 0, limit: int = 100,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    notes = entity_note_service.get_notes_for_lead(
        db=db, lead_id=lead_id, company_id=current_user.company_id,
        note_type=NoteTypeModel(note_type.value) if note_type else None,
        skip=skip, limit=limit
    )
    total = entity_note_service.count_notes_for_lead(db=db, lead_id=lead_id, company_id=current_user.company_id)
    return _to_list(notes, total)


@router.get("/deal/{deal_id}", response_model=EntityNoteList)
def get_notes_for_deal(
    deal_id: int,
    note_type: Optional[NoteType] = None,
    skip: int = 0, limit: int = 100,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    notes = entity_note_service.get_notes_for_deal(
        db=db, deal_id=deal_id, company_id=current_user.company_id,
        note_type=NoteTypeModel(note_type.value) if note_type else None,
        skip=skip, limit=limit
    )
    total = entity_note_service.count_notes_for_deal(db=db, deal_id=deal_id, company_id=current_user.company_id)
    return _to_list(notes, total)


@router.get("/account/{account_id}", response_model=EntityNoteList)
def get_notes_for_account(
    account_id: int,
    note_type: Optional[NoteType] = None,
    skip: int = 0, limit: int = 100,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    notes = entity_note_service.get_notes_for_account(
        db=db, account_id=account_id, company_id=current_user.company_id,
        note_type=NoteTypeModel(note_type.value) if note_type else None,
        skip=skip, limit=limit
    )
    total = entity_note_service.count_notes_for_account(db=db, account_id=account_id, company_id=current_user.company_id)
    return _to_list(notes, total)


@router.get("/{note_id}", response_model=EntityNoteResponse)
def get_note(
    note_id: int,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    note = entity_note_service.get_note(db=db, note_id=note_id, company_id=current_user.company_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    return _to_response(note)


@router.put("/{note_id}", response_model=EntityNoteResponse)
def update_note(
    note_id: int,
    note: EntityNoteUpdate,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    updated = entity_note_service.update_note(
        db=db, note_id=note_id, note_data=note,
        company_id=current_user.company_id, user_id=current_user.id
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Note not found")
    return _to_response(updated)


@router.delete("/{note_id}")
def delete_note(
    note_id: int,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    if not entity_note_service.delete_note(db=db, note_id=note_id, company_id=current_user.company_id):
        raise HTTPException(status_code=404, detail="Note not found")
    return {"success": True}
