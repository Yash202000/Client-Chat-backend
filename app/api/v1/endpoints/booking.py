"""
Booking link endpoints.
Public (no-auth): GET /{slug}, GET /{slug}/slots, POST /{slug}/book
Authenticated: CRUD for booking links, GET /{id}/bookings
"""
from datetime import datetime, date
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, get_current_active_user
from app.services import booking_service
from app.models import user as models_user

router = APIRouter()


# ── Schemas ──────────────────────────────────────────────────────────────────

class AvailabilityWindow(BaseModel):
    start: str  # "09:00"
    end: str    # "17:00"


class BookingLinkCreate(BaseModel):
    title: str
    description: Optional[str] = None
    location: Optional[str] = None
    slug: Optional[str] = None
    duration_minutes: int = 30
    buffer_before_minutes: int = 0
    buffer_after_minutes: int = 0
    availability: Optional[dict] = None
    timezone: str = "UTC"
    max_advance_days: int = 60
    min_notice_hours: int = 1
    color: str = "#6366f1"
    is_active: bool = True


class BookingLinkUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None
    duration_minutes: Optional[int] = None
    buffer_before_minutes: Optional[int] = None
    buffer_after_minutes: Optional[int] = None
    availability: Optional[dict] = None
    timezone: Optional[str] = None
    max_advance_days: Optional[int] = None
    min_notice_hours: Optional[int] = None
    color: Optional[str] = None
    is_active: Optional[bool] = None


class BookingLinkOut(BaseModel):
    id: int
    slug: str
    title: str
    description: Optional[str] = None
    location: Optional[str] = None
    duration_minutes: int
    buffer_before_minutes: int
    buffer_after_minutes: int
    availability: dict
    timezone: str
    max_advance_days: int
    min_notice_hours: int
    color: Optional[str] = None
    is_active: bool
    owner_name: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class BookingRequest(BaseModel):
    start_time: datetime
    booker_name: str
    booker_email: str
    booker_phone: Optional[str] = None
    booker_notes: Optional[str] = None


class BookingSlotOut(BaseModel):
    id: int
    booker_name: str
    booker_email: str
    booker_phone: Optional[str] = None
    booker_notes: Optional[str] = None
    start_time: datetime
    end_time: datetime
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


# ── Public endpoints (no auth) ───────────────────────────────────────────────

@router.get("/public/{slug}", response_model=BookingLinkOut)
def get_public_booking_link(slug: str, db: Session = Depends(get_db)):
    link = booking_service.get_booking_link(db=db, slug=slug)
    if not link:
        raise HTTPException(status_code=404, detail="Booking link not found")
    out = BookingLinkOut(
        id=link.id, slug=link.slug, title=link.title, description=link.description,
        location=link.location, duration_minutes=link.duration_minutes,
        buffer_before_minutes=link.buffer_before_minutes,
        buffer_after_minutes=link.buffer_after_minutes,
        availability=link.availability or {}, timezone=link.timezone,
        max_advance_days=link.max_advance_days, min_notice_hours=link.min_notice_hours,
        color=link.color, is_active=link.is_active,
        owner_name=f"{link.owner.first_name or ''} {link.owner.last_name or ''}".strip() if link.owner else None,
        created_at=link.created_at,
    )
    return out


@router.get("/public/{slug}/slots")
def get_available_slots(
    slug: str,
    date: str = Query(..., description="YYYY-MM-DD"),
    db: Session = Depends(get_db),
):
    link = booking_service.get_booking_link(db=db, slug=slug)
    if not link:
        raise HTTPException(status_code=404, detail="Booking link not found")
    try:
        target_date = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format, expected YYYY-MM-DD")
    slots = booking_service.get_available_slots(db=db, link=link, target_date=target_date)
    return {"slots": slots}


@router.post("/public/{slug}/book", response_model=BookingSlotOut)
def create_booking(slug: str, payload: BookingRequest, db: Session = Depends(get_db)):
    link = booking_service.get_booking_link(db=db, slug=slug)
    if not link:
        raise HTTPException(status_code=404, detail="Booking link not found")
    try:
        slot = booking_service.create_booking(
            db=db, link=link,
            start_time=payload.start_time,
            booker_name=payload.booker_name,
            booker_email=payload.booker_email,
            booker_phone=payload.booker_phone,
            booker_notes=payload.booker_notes,
        )
        return slot
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── Authenticated management endpoints ──────────────────────────────────────

@router.get("/", response_model=List[BookingLinkOut])
def list_my_booking_links(
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user),
):
    links = booking_service.get_booking_links_for_user(
        db=db, user_id=current_user.id, company_id=current_user.company_id
    )
    return [
        BookingLinkOut(
            id=l.id, slug=l.slug, title=l.title, description=l.description,
            location=l.location, duration_minutes=l.duration_minutes,
            buffer_before_minutes=l.buffer_before_minutes,
            buffer_after_minutes=l.buffer_after_minutes,
            availability=l.availability or {}, timezone=l.timezone,
            max_advance_days=l.max_advance_days, min_notice_hours=l.min_notice_hours,
            color=l.color, is_active=l.is_active,
            owner_name=f"{current_user.first_name or ''} {current_user.last_name or ''}".strip(),
            created_at=l.created_at,
        )
        for l in links
    ]


@router.post("/", response_model=BookingLinkOut)
def create_booking_link(
    payload: BookingLinkCreate,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user),
):
    link = booking_service.create_booking_link(
        db=db, data=payload.model_dump(exclude_none=True),
        user_id=current_user.id, company_id=current_user.company_id,
    )
    return BookingLinkOut(
        id=link.id, slug=link.slug, title=link.title, description=link.description,
        location=link.location, duration_minutes=link.duration_minutes,
        buffer_before_minutes=link.buffer_before_minutes,
        buffer_after_minutes=link.buffer_after_minutes,
        availability=link.availability or {}, timezone=link.timezone,
        max_advance_days=link.max_advance_days, min_notice_hours=link.min_notice_hours,
        color=link.color, is_active=link.is_active,
        owner_name=f"{current_user.first_name or ''} {current_user.last_name or ''}".strip(),
        created_at=link.created_at,
    )


@router.put("/{link_id}", response_model=BookingLinkOut)
def update_booking_link(
    link_id: int,
    payload: BookingLinkUpdate,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user),
):
    link = booking_service.update_booking_link(
        db=db, link_id=link_id,
        data=payload.model_dump(exclude_unset=True),
        company_id=current_user.company_id,
    )
    if not link:
        raise HTTPException(status_code=404, detail="Booking link not found")
    return BookingLinkOut(
        id=link.id, slug=link.slug, title=link.title, description=link.description,
        location=link.location, duration_minutes=link.duration_minutes,
        buffer_before_minutes=link.buffer_before_minutes,
        buffer_after_minutes=link.buffer_after_minutes,
        availability=link.availability or {}, timezone=link.timezone,
        max_advance_days=link.max_advance_days, min_notice_hours=link.min_notice_hours,
        color=link.color, is_active=link.is_active,
        owner_name=f"{current_user.first_name or ''} {current_user.last_name or ''}".strip(),
        created_at=link.created_at,
    )


@router.delete("/{link_id}")
def delete_booking_link(
    link_id: int,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user),
):
    if not booking_service.delete_booking_link(db=db, link_id=link_id, company_id=current_user.company_id):
        raise HTTPException(status_code=404, detail="Booking link not found")
    return {"ok": True}


@router.get("/{link_id}/bookings", response_model=List[BookingSlotOut])
def get_bookings(
    link_id: int,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user),
):
    link = booking_service.get_booking_link_by_id(
        db=db, link_id=link_id, company_id=current_user.company_id
    )
    if not link:
        raise HTTPException(status_code=404, detail="Booking link not found")
    return link.slots
