from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel

from app.core.dependencies import get_db, get_current_active_user
from app.models.user import User
from app.models.contact import Contact
from app.models.contact_activity import ContactActivity
from app.models.entity_note import EntityNote

router = APIRouter()


# ── Schemas ──────────────────────────────────────────────────────────────────

class TimelineItem(BaseModel):
    id: int
    activity_type: str
    title: str
    description: Optional[str] = None
    entity_type: Optional[str] = None
    entity_id: Optional[int] = None
    user_id: Optional[int] = None
    occurred_at: datetime
    source: str  # "activity" | "note"

    class Config:
        from_attributes = True


class ActivityLogRequest(BaseModel):
    activity_type: str
    title: str
    description: Optional[str] = None
    occurred_at: Optional[datetime] = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_contact_or_404(db: Session, contact_id: int, company_id: int) -> Contact:
    contact = db.query(Contact).filter(
        Contact.id == contact_id,
        Contact.company_id == company_id,
    ).first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    return contact


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/{contact_id}/timeline", response_model=List[TimelineItem])
def get_contact_timeline(
    contact_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Return the merged activity timeline for a contact (activities + entity notes)."""
    _get_contact_or_404(db, contact_id, current_user.company_id)

    # Fetch ContactActivity records
    activities = (
        db.query(ContactActivity)
        .filter(
            ContactActivity.contact_id == contact_id,
            ContactActivity.company_id == current_user.company_id,
        )
        .order_by(ContactActivity.occurred_at.desc())
        .limit(50)
        .all()
    )

    # Fetch EntityNote records for this contact
    notes = (
        db.query(EntityNote)
        .filter(
            EntityNote.contact_id == contact_id,
            EntityNote.company_id == current_user.company_id,
        )
        .order_by(EntityNote.created_at.desc())
        .limit(50)
        .all()
    )

    # Build unified list
    items: List[TimelineItem] = []

    for a in activities:
        items.append(TimelineItem(
            id=a.id,
            activity_type=a.activity_type,
            title=a.title,
            description=a.description,
            entity_type=a.entity_type,
            entity_id=a.entity_id,
            user_id=a.user_id,
            occurred_at=a.occurred_at,
            source="activity",
        ))

    for n in notes:
        items.append(TimelineItem(
            id=n.id,
            activity_type=n.note_type.value if hasattr(n.note_type, "value") else str(n.note_type),
            title=n.title or f"{n.note_type} note",
            description=n.content,
            entity_type=None,
            entity_id=None,
            user_id=n.created_by,
            occurred_at=n.activity_date or n.created_at,
            source="note",
        ))

    # Sort merged list by occurred_at descending
    items.sort(key=lambda x: x.occurred_at, reverse=True)

    return items[:50]


@router.post("/{contact_id}/timeline", response_model=TimelineItem)
def log_contact_activity(
    contact_id: int,
    body: ActivityLogRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Manually log an activity against a contact."""
    _get_contact_or_404(db, contact_id, current_user.company_id)

    activity = ContactActivity(
        contact_id=contact_id,
        company_id=current_user.company_id,
        activity_type=body.activity_type,
        title=body.title,
        description=body.description,
        user_id=current_user.id,
        occurred_at=body.occurred_at or datetime.utcnow(),
    )
    db.add(activity)
    db.commit()
    db.refresh(activity)

    return TimelineItem(
        id=activity.id,
        activity_type=activity.activity_type,
        title=activity.title,
        description=activity.description,
        entity_type=activity.entity_type,
        entity_id=activity.entity_id,
        user_id=activity.user_id,
        occurred_at=activity.occurred_at,
        source="activity",
    )
