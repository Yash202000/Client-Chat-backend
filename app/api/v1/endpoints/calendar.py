from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional, Dict
from datetime import datetime, timedelta

from app.core.dependencies import get_db, get_current_active_user
from app.models.user import User as UserModel
from app.models.calendar_event import CalendarEvent
from app.schemas.calendar_event import CalendarEventCreate, CalendarEventUpdate, CalendarEventOut

router = APIRouter()


# ─── Recurrence helper ────────────────────────────────────────────────────────

def _expand_recurring(parent: CalendarEvent, payload: CalendarEventCreate, db: Session):
    from dateutil.relativedelta import relativedelta

    rule = payload.recurrence_rule
    if not rule:
        return

    interval = payload.recurrence_interval or 1
    end_date = payload.recurrence_end_date

    if end_date is None:
        end_date = parent.start_time + relativedelta(months=3)

    current_start = parent.start_time
    current_end = parent.end_time
    max_count = 52

    for _ in range(max_count):
        if rule == 'daily':
            current_start = current_start + timedelta(days=interval)
            current_end = current_end + timedelta(days=interval)
        elif rule == 'weekly':
            current_start = current_start + timedelta(weeks=interval)
            current_end = current_end + timedelta(weeks=interval)
        elif rule == 'monthly':
            current_start = current_start + relativedelta(months=interval)
            current_end = current_end + relativedelta(months=interval)
        else:
            break

        if current_start > end_date:
            break

        instance = CalendarEvent(
            title=parent.title,
            event_type=parent.event_type,
            start_time=current_start,
            end_time=current_end,
            is_all_day=parent.is_all_day,
            location=parent.location,
            description=parent.description,
            attendees=parent.attendees,
            livekit_room_name=parent.livekit_room_name,
            recurrence_rule=parent.recurrence_rule,
            recurrence_interval=parent.recurrence_interval,
            recurrence_end_date=parent.recurrence_end_date,
            parent_event_id=parent.id,
            user_id=parent.user_id,
            company_id=parent.company_id,
        )
        db.add(instance)


# ─── Routes ───────────────────────────────────────────────────────────────────

@router.get("/events", response_model=List[CalendarEventOut])
def list_events(
    start: Optional[datetime] = Query(None),
    end: Optional[datetime] = Query(None),
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_active_user),
):
    q = db.query(CalendarEvent).filter(CalendarEvent.company_id == current_user.company_id)
    if start is not None:
        q = q.filter(CalendarEvent.start_time >= start)
    if end is not None:
        q = q.filter(CalendarEvent.end_time <= end)
    return q.order_by(CalendarEvent.start_time).all()


@router.post("/events", response_model=CalendarEventOut, status_code=201)
def create_event(
    payload: CalendarEventCreate,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_active_user),
):
    event = CalendarEvent(
        **payload.model_dump(),
        user_id=current_user.id,
        company_id=current_user.company_id,
    )
    db.add(event)
    db.flush()  # assign event.id before expanding instances

    if payload.recurrence_rule:
        _expand_recurring(event, payload, db)

    db.commit()
    db.refresh(event)
    return event


@router.put("/events/{event_id}", response_model=CalendarEventOut)
def update_event(
    event_id: int,
    payload: CalendarEventUpdate,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_active_user),
):
    event = db.query(CalendarEvent).filter(CalendarEvent.id == event_id).first()
    if event is None:
        raise HTTPException(status_code=404, detail="Calendar event not found")
    if event.company_id != current_user.company_id:
        raise HTTPException(status_code=403, detail="Not authorised to update this event")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(event, field, value)

    db.commit()
    db.refresh(event)
    return event


@router.delete("/events/{event_id}", status_code=204)
def delete_event(
    event_id: int,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_active_user),
):
    event = db.query(CalendarEvent).filter(CalendarEvent.id == event_id).first()
    if event is None:
        raise HTTPException(status_code=404, detail="Calendar event not found")
    if event.company_id != current_user.company_id:
        raise HTTPException(status_code=403, detail="Not authorised to delete this event")

    db.delete(event)
    db.commit()


@router.post("/events/{event_id}/join-meeting")
def join_meeting(
    event_id: int,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_active_user),
):
    event = db.query(CalendarEvent).filter(CalendarEvent.id == event_id).first()
    if event is None:
        raise HTTPException(status_code=404, detail="Calendar event not found")
    if event.company_id != current_user.company_id:
        raise HTTPException(status_code=403, detail="Not authorised")
    if not event.livekit_room_name:
        raise HTTPException(status_code=400, detail="This event has no video meeting room")

    # Create or reuse the meeting chat channel
    if not event.channel_id:
        from app.crud import crud_chat
        from app.schemas.chat import ChatChannelCreate
        from app.models.user import User as UserModel2

        # Resolve attendee emails to user IDs within the same company
        attendee_ids: list[int] = []
        if event.attendees:
            attendee_users = (
                db.query(UserModel2)
                .filter(
                    UserModel2.email.in_(event.attendees),
                    UserModel2.company_id == event.company_id,
                    UserModel2.id != event.user_id,
                )
                .all()
            )
            attendee_ids = [u.id for u in attendee_users]

        channel_schema = ChatChannelCreate(
            name=event.title,
            description=f"Meeting chat — {event.title}",
            channel_type="MEETING",
            member_ids=attendee_ids,
        )
        channel = crud_chat.create_channel(
            db=db,
            channel=channel_schema,
            creator_id=event.user_id,
            company_id=event.company_id,
        )
        event.channel_id = channel.id
        db.commit()
        db.refresh(event)

    # Ensure the joining user is a channel member (idempotent)
    from app.crud import crud_chat as _crud_chat
    from app.models import ChannelMembership
    already_member = db.query(ChannelMembership).filter(
        ChannelMembership.channel_id == event.channel_id,
        ChannelMembership.user_id == current_user.id,
    ).first()
    if not already_member:
        _crud_chat.add_user_to_channel(db, user_id=current_user.id, channel_id=event.channel_id)

    from app.services.livekit_service import generate_livekit_token
    from app.core.config import settings

    identity = f"user-{current_user.id}"
    display_name = current_user.first_name or current_user.email
    token = generate_livekit_token(event.livekit_room_name, identity, display_name)

    return {
        "token": token,
        "room_name": event.livekit_room_name,
        "livekit_url": settings.LIVEKIT_URL,
        "channel_id": event.channel_id,
    }


@router.get("/availability", response_model=Dict[str, List[CalendarEventOut]])
def get_availability(
    user_ids: str = Query(...),
    start: datetime = Query(...),
    end: datetime = Query(...),
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_active_user),
):
    ids = [int(i.strip()) for i in user_ids.split(",") if i.strip().isdigit()]
    if not ids:
        return {}

    events = (
        db.query(CalendarEvent)
        .filter(
            CalendarEvent.company_id == current_user.company_id,
            CalendarEvent.user_id.in_(ids),
            CalendarEvent.start_time < end,
            CalendarEvent.end_time > start,
        )
        .all()
    )

    result: Dict[str, list] = {str(uid): [] for uid in ids}
    for ev in events:
        key = str(ev.user_id)
        if key in result:
            result[key].append(ev)
    return result
