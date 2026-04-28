from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime

from app.core.dependencies import get_db, get_current_active_user
from app.models.user import User as UserModel
from app.models.calendar_event import CalendarEvent
from app.schemas.calendar_event import CalendarEventCreate, CalendarEventUpdate, CalendarEventOut

router = APIRouter()


@router.get("/events", response_model=List[CalendarEventOut])
def list_events(
    start: Optional[datetime] = Query(None, description="Filter events starting at or after this ISO datetime"),
    end: Optional[datetime] = Query(None, description="Filter events ending at or before this ISO datetime"),
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_active_user),
):
    """List all calendar events for the current user's company, optionally filtered by a datetime range."""
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
    """Create a new calendar event owned by the current user."""
    event = CalendarEvent(
        **payload.model_dump(),
        user_id=current_user.id,
        company_id=current_user.company_id,
    )
    db.add(event)
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
    """Update a calendar event. Only the owner or a user in the same company may update."""
    event = db.query(CalendarEvent).filter(CalendarEvent.id == event_id).first()
    if event is None:
        raise HTTPException(status_code=404, detail="Calendar event not found")
    if event.company_id != current_user.company_id:
        raise HTTPException(status_code=403, detail="Not authorised to update this event")

    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
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
    """Delete a calendar event. Only the owner or a user in the same company may delete."""
    event = db.query(CalendarEvent).filter(CalendarEvent.id == event_id).first()
    if event is None:
        raise HTTPException(status_code=404, detail="Calendar event not found")
    if event.company_id != current_user.company_id:
        raise HTTPException(status_code=403, detail="Not authorised to delete this event")

    db.delete(event)
    db.commit()
