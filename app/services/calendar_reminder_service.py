"""
Calendar reminder service.

Runs every minute via APScheduler. Finds events starting in ~5 minutes or
right now, and pushes a `calendar_reminder` WebSocket event to each attendee
via manager.broadcast_to_user so the frontend shows the reminder immediately.
"""
from datetime import datetime, timedelta, timezone
from app.core.database import SessionLocal
from app.models.calendar_event import CalendarEvent
from app.schemas.websockets import WebSocketMessage
from app.services.connection_manager import manager

# Key: "{event_id}_{threshold}" — reset on server restart (acceptable)
_fired: set[str] = set()

THRESHOLDS = [5, 0]  # minutes before start to fire a reminder


async def run_calendar_reminder_scheduler():
    with SessionLocal() as db:
        now = datetime.now(timezone.utc)
        # Fetch events in a 10-minute window so we catch both thresholds
        window_start = now
        window_end = now + timedelta(minutes=7)

        events = (
            db.query(CalendarEvent)
            .filter(
                CalendarEvent.start_time >= window_start,
                CalendarEvent.start_time <= window_end,
            )
            .all()
        )

        for event in events:
            start = event.start_time
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
            mins_until = (start - now).total_seconds() / 60

            for threshold in THRESHOLDS:
                key = f"{event.id}_{threshold}"
                # Fire when we enter the [threshold-1, threshold+1] window
                if abs(mins_until - threshold) <= 1 and key not in _fired:
                    _fired.add(key)
                    await _push_reminder(event, mins_until)


async def _push_reminder(event: CalendarEvent, mins_until: float):
    label = "Starting now" if mins_until <= 1 else f"in {round(mins_until)} minutes"
    payload = {
        "event_id": event.id,
        "title": event.title,
        "start_time": event.start_time.isoformat(),
        "location": event.location,
        "livekit_room_name": event.livekit_room_name,
        "label": label,
    }
    msg = WebSocketMessage(type="calendar_reminder", payload=payload).model_dump_json()

    # Notify the event owner
    await manager.broadcast_to_user(event.user_id, msg)

    # Also notify any attendees who are users in the same company
    # (attendees are stored as email strings; skip if not resolvable)
    if event.attendees:
        with SessionLocal() as db:
            from app.models.user import User
            attendee_users = (
                db.query(User)
                .filter(
                    User.email.in_(event.attendees),
                    User.company_id == event.company_id,
                    User.id != event.user_id,
                )
                .all()
            )
            for u in attendee_users:
                await manager.broadcast_to_user(u.id, msg)
