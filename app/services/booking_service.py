import re
import uuid
from datetime import datetime, timedelta, date, time
from typing import List, Optional, Dict
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from sqlalchemy.orm import Session

from app.models.booking_link import BookingLink, BookingSlot, BookingSlotStatus
from app.models.calendar_event import CalendarEvent
from app.models.contact import Contact
from app.models.lead import Lead


DEFAULT_AVAILABILITY = {
    "monday":    [{"start": "09:00", "end": "17:00"}],
    "tuesday":   [{"start": "09:00", "end": "17:00"}],
    "wednesday": [{"start": "09:00", "end": "17:00"}],
    "thursday":  [{"start": "09:00", "end": "17:00"}],
    "friday":    [{"start": "09:00", "end": "17:00"}],
    "saturday":  [],
    "sunday":    [],
}

DAY_NAMES = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def _tz(tz_str: str) -> ZoneInfo:
    try:
        return ZoneInfo(tz_str)
    except (ZoneInfoNotFoundError, Exception):
        return ZoneInfo("UTC")


def _parse_hhmm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def get_booking_link(db: Session, slug: str) -> Optional[BookingLink]:
    return db.query(BookingLink).filter(
        BookingLink.slug == slug, BookingLink.is_active == True
    ).first()


def get_booking_link_by_id(db: Session, link_id: int, company_id: int) -> Optional[BookingLink]:
    return db.query(BookingLink).filter(
        BookingLink.id == link_id, BookingLink.company_id == company_id
    ).first()


def get_booking_links_for_user(db: Session, user_id: int, company_id: int) -> List[BookingLink]:
    return db.query(BookingLink).filter(
        BookingLink.user_id == user_id,
        BookingLink.company_id == company_id,
    ).order_by(BookingLink.created_at.desc()).all()


def _slug_from_title(title: str) -> str:
    slug = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')
    return f"{slug}-{uuid.uuid4().hex[:6]}"


def create_booking_link(db: Session, data: dict, user_id: int, company_id: int) -> BookingLink:
    slug = data.get("slug") or _slug_from_title(data.get("title", "meeting"))
    # Ensure slug uniqueness
    base_slug = slug
    counter = 1
    while db.query(BookingLink).filter(BookingLink.slug == slug).first():
        slug = f"{base_slug}-{counter}"
        counter += 1

    link = BookingLink(
        company_id=company_id,
        user_id=user_id,
        slug=slug,
        title=data["title"],
        description=data.get("description"),
        location=data.get("location"),
        duration_minutes=data.get("duration_minutes", 30),
        buffer_before_minutes=data.get("buffer_before_minutes", 0),
        buffer_after_minutes=data.get("buffer_after_minutes", 0),
        availability=data.get("availability", DEFAULT_AVAILABILITY),
        date_overrides=data.get("date_overrides", {}),
        timezone=data.get("timezone", "UTC"),
        max_advance_days=data.get("max_advance_days", 60),
        min_notice_hours=data.get("min_notice_hours", 1),
        color=data.get("color", "#6366f1"),
        is_active=data.get("is_active", True),
    )
    db.add(link)
    db.commit()
    db.refresh(link)
    return link


def update_booking_link(db: Session, link_id: int, data: dict, company_id: int) -> Optional[BookingLink]:
    link = db.query(BookingLink).filter(
        BookingLink.id == link_id, BookingLink.company_id == company_id
    ).first()
    if not link:
        return None
    for k, v in data.items():
        if k != "slug" and hasattr(link, k):
            setattr(link, k, v)
    db.commit()
    db.refresh(link)
    return link


def delete_booking_link(db: Session, link_id: int, company_id: int) -> bool:
    link = db.query(BookingLink).filter(
        BookingLink.id == link_id, BookingLink.company_id == company_id
    ).first()
    if not link:
        return False
    db.delete(link)
    db.commit()
    return True


def get_available_slots(db: Session, link: BookingLink, target_date: date) -> List[Dict]:
    """
    Returns list of {start, end} UTC datetimes available on target_date.
    Respects date_overrides first, then weekly availability windows, plus
    existing calendar events, buffers, and notice period.
    """
    tz = _tz(link.timezone)
    date_key = target_date.strftime("%Y-%m-%d")
    overrides = link.date_overrides or {}

    if date_key in overrides:
        # explicit override for this date: [] = blocked, [...] = custom hours
        windows = overrides[date_key]
    else:
        day_name = DAY_NAMES[target_date.weekday()]
        windows = (link.availability or {}).get(day_name, [])

    if not windows:
        return []

    duration = timedelta(minutes=link.duration_minutes)
    buf_before = timedelta(minutes=link.buffer_before_minutes)
    buf_after = timedelta(minutes=link.buffer_after_minutes)
    min_notice = timedelta(hours=link.min_notice_hours)
    now_utc = datetime.utcnow()

    # Fetch existing calendar events for this user on target_date (with padding)
    day_start_utc = datetime.combine(target_date, time.min)
    day_end_utc = datetime.combine(target_date, time.max)
    existing = db.query(CalendarEvent).filter(
        CalendarEvent.user_id == link.user_id,
        CalendarEvent.start_time < day_end_utc,
        CalendarEvent.end_time > day_start_utc,
    ).all()

    busy_intervals = []
    for ev in existing:
        start = ev.start_time.replace(tzinfo=None) if ev.start_time.tzinfo else ev.start_time
        end = ev.end_time.replace(tzinfo=None) if ev.end_time.tzinfo else ev.end_time
        busy_intervals.append((start - buf_before, end + buf_after))

    # Also mark already-booked slots as busy
    booked = db.query(BookingSlot).filter(
        BookingSlot.booking_link_id == link.id,
        BookingSlot.status != BookingSlotStatus.CANCELLED,
        BookingSlot.start_time >= day_start_utc,
        BookingSlot.start_time < day_end_utc,
    ).all()
    for slot in booked:
        busy_intervals.append((slot.start_time - buf_before, slot.end_time + buf_after))

    slots = []
    for window in windows:
        w_start = _parse_hhmm(window["start"])
        w_end = _parse_hhmm(window["end"])

        # Convert window to UTC
        local_start = datetime.combine(target_date, w_start).replace(tzinfo=tz)
        local_end = datetime.combine(target_date, w_end).replace(tzinfo=tz)
        utc_start = local_start.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
        utc_end = local_end.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)

        current = utc_start
        while current + duration <= utc_end:
            slot_end = current + duration
            # Check minimum notice
            if current < now_utc + min_notice:
                current += timedelta(minutes=15)
                continue
            # Check against busy intervals
            overlap = any(
                current < busy_end and slot_end > busy_start
                for busy_start, busy_end in busy_intervals
            )
            if not overlap:
                slots.append({"start": current.isoformat(), "end": slot_end.isoformat()})
            current += timedelta(minutes=15)

    return slots


def create_booking(
    db: Session,
    link: BookingLink,
    start_time: datetime,
    booker_name: str,
    booker_email: str,
    booker_phone: Optional[str],
    booker_notes: Optional[str],
) -> BookingSlot:
    end_time = start_time + timedelta(minutes=link.duration_minutes)

    # Try to match or create a Contact
    contact = db.query(Contact).filter(
        Contact.email == booker_email,
        Contact.company_id == link.company_id,
    ).first()
    if not contact:
        contact = Contact(
            email=booker_email,
            name=booker_name,
            phone_number=booker_phone,
            company_id=link.company_id,
            lead_source="booking_link",
        )
        db.add(contact)
        db.flush()

    # Auto-create a lead if one doesn't exist for this contact
    existing_lead = db.query(Lead).filter(
        Lead.contact_id == contact.id,
        Lead.company_id == link.company_id,
    ).first()
    if not existing_lead:
        from app.services import lead_service
        from app.schemas.lead import LeadCreate
        lead_service.create_lead(
            db=db,
            lead=LeadCreate(contact_id=contact.id, source="booking_link"),
            company_id=link.company_id,
        )

    # Create CalendarEvent for the host
    event = CalendarEvent(
        company_id=link.company_id,
        user_id=link.user_id,
        title=f"{link.title} with {booker_name}",
        event_type="meeting",
        start_time=start_time,
        end_time=end_time,
        location=link.location or "",
        description=booker_notes or "",
        attendees=[booker_email],
    )
    db.add(event)
    db.flush()

    booking_slot = BookingSlot(
        booking_link_id=link.id,
        calendar_event_id=event.id,
        booker_name=booker_name,
        booker_email=booker_email,
        booker_phone=booker_phone,
        booker_notes=booker_notes,
        start_time=start_time,
        end_time=end_time,
        status=BookingSlotStatus.CONFIRMED,
        contact_id=contact.id,
    )
    db.add(booking_slot)
    db.commit()
    db.refresh(booking_slot)
    return booking_slot
