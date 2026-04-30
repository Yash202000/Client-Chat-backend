
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime, timezone
from app.core.dependencies import get_db, get_current_user
from app.core.config import settings
from app.models.user import User
from app.models.voice_call import VoiceCall
from app.models.video_call import VideoCall
from app.models.chat_channel import ChatChannel
from app.models.calendar_event import CalendarEvent
from app.services.connection_manager import manager
from app.services import agent_assignment_service
from livekit import api
import json

from app.schemas.call import StartCallRequest
from pydantic import BaseModel

router = APIRouter()

class AcceptCallRequest(BaseModel):
    session_id: str
    room_name: str
    livekit_url: str
    user_token: str

class RejectCallRequest(BaseModel):
    session_id: str
    reason: str = "Agent declined"

@router.post("/start")
def start_call(request: StartCallRequest, db: Session = Depends(get_db)):
    # For now, we just return a success message.
    # In a real implementation, you might create a record of the call in the database.
    return {"message": f"Call started for session {request.session_id}"}

@router.get("/token")
def get_join_token(session_id: str, user_id: str, db: Session = Depends(get_db)):
    if not settings.LIVEKIT_URL or not settings.LIVEKIT_API_KEY or not settings.LIVEKIT_API_SECRET:
        raise HTTPException(status_code=500, detail="LiveKit is not configured.")

    token = api.AccessToken(
        settings.LIVEKIT_API_KEY,
        settings.LIVEKIT_API_SECRET
    ).with_identity(user_id).with_name(user_id).with_grants(
        api.VideoGrants(room_join=True, room=session_id)
    )

    return {"token": token.to_jwt()}

@router.post("/accept")
async def accept_call(
    request: AcceptCallRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Agent accepts an incoming call. Assigns the session to the agent and notifies the customer.
    """
    try:
        # Get the session
        from app.services import conversation_session_service
        session = conversation_session_service.get_session(db, request.session_id)

        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        # Assign the session to the agent
        team_name = session.assigned_pool or "Support"
        await agent_assignment_service.assign_session_to_agent(
            db=db,
            session_id=request.session_id,
            agent_user_id=current_user.id,
            company_id=session.company_id,
            reason="call_accepted",
            team_name=team_name
        )

        # Broadcast call accepted message to the customer
        call_accepted_message = {
            "type": "call_accepted",
            "session_id": request.session_id,
            "agent_name": f"{current_user.first_name} {current_user.last_name}".strip() or current_user.email,
            "room_name": request.room_name,
            "livekit_url": request.livekit_url,
            "user_token": request.user_token
        }

        # Broadcast to the session (customer's widget)
        await manager.broadcast_to_session(request.session_id, json.dumps(call_accepted_message), "agent")

        return {
            "status": "accepted",
            "session_id": request.session_id,
            "room_name": request.room_name
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to accept call: {str(e)}")

@router.post("/reject")
async def reject_call(
    request: RejectCallRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Agent rejects an incoming call. Notifies the customer and resets the session state.
    """
    try:
        # Get the session
        from app.services import conversation_session_service
        from app.schemas.conversation_session import ConversationSessionUpdate
        from datetime import datetime

        session = conversation_session_service.get_session(db, request.session_id)

        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        # Update session to reset handoff state
        session_update = ConversationSessionUpdate(
            waiting_for_agent=False,
            status='active',
            is_ai_enabled=True  # Re-enable AI
        )

        conversation_session_service.update_session(db, request.session_id, session_update)

        # Broadcast call rejected message to the customer
        call_rejected_message = {
            "type": "call_rejected",
            "session_id": request.session_id,
            "reason": request.reason,
            "message": "The agent is currently unavailable. You can continue chatting with our AI assistant."
        }

        # Broadcast to the session (customer's widget)
        await manager.broadcast_to_session(request.session_id, json.dumps(call_rejected_message), "agent")

        return {
            "status": "rejected",
            "session_id": request.session_id
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to reject call: {str(e)}")


# ─── Unified Call Log ─────────────────────────────────────────────────────────

MISSED_VOICE_STATUSES = {"no_answer", "failed", "busy", "missed"}
MISSED_VIDEO_STATUSES = {"missed", "rejected"}

@router.get("/log")
def get_unified_call_log(
    call_type: Optional[str] = Query(None, description="voice | video | meeting"),
    direction: Optional[str] = Query(None, description="inbound | outbound | internal"),
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    show_missed: bool = Query(False),
    limit: int = Query(100, le=500),
    skip: int = Query(0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Returns a unified, time-sorted log of all call types:
    voice (Twilio), video (internal channel calls), and meeting (calendar events with video).
    """
    entries = []

    # ── 1. Twilio voice calls ─────────────────────────────────────────────────
    if not call_type or call_type == "voice":
        q = db.query(VoiceCall).filter(VoiceCall.company_id == current_user.company_id)
        if direction and direction in ("inbound", "outbound"):
            q = q.filter(VoiceCall.direction == direction)
        elif direction == "internal":
            q = q.filter(False)  # voice calls are never "internal"
        if show_missed:
            q = q.filter(VoiceCall.status.in_(list(MISSED_VOICE_STATUSES)))
        elif status:
            q = q.filter(VoiceCall.status == status)
        if search:
            s = f"%{search}%"
            q = q.filter((VoiceCall.from_number.ilike(s)) | (VoiceCall.to_number.ilike(s)))
        for vc in q.order_by(VoiceCall.started_at.desc()).all():
            entries.append({
                "id": f"voice-{vc.id}",
                "source_id": vc.id,
                "call_type": "voice",
                "direction": vc.direction,
                "status": vc.status,
                "started_at": vc.started_at.isoformat() if vc.started_at else None,
                "ended_at": vc.ended_at.isoformat() if vc.ended_at else None,
                "duration_seconds": vc.duration_seconds,
                "title": vc.from_number if vc.direction == "inbound" else vc.to_number,
                "from_number": vc.from_number,
                "to_number": vc.to_number,
                "recording_url": vc.recording_url,
                "recording_duration_secs": vc.recording_duration_secs,
                "full_transcript": vc.full_transcript,
                "csat_score": vc.csat_score,
                "channel_id": None,
                "channel_name": None,
                "event_id": None,
                "event_title": None,
                "attendees": None,
                "participants": [],
            })

    # ── 2. Internal video calls (team/channel calls) ──────────────────────────
    if not call_type or call_type == "video":
        if not direction or direction == "internal":
            q = (
                db.query(VideoCall)
                .join(ChatChannel, VideoCall.channel_id == ChatChannel.id)
                .filter(ChatChannel.company_id == current_user.company_id)
            )
            if show_missed:
                q = q.filter(VideoCall.status.in_(list(MISSED_VIDEO_STATUSES)))
            elif status:
                q = q.filter(VideoCall.status == status)
            for vc in q.order_by(VideoCall.started_at.desc()).all():
                duration_seconds = None
                if vc.answered_at and vc.ended_at:
                    duration_seconds = int((vc.ended_at - vc.answered_at).total_seconds())

                channel_name = vc.channel.name if vc.channel else None

                # Resolve participant display names
                participants = []
                if vc.joined_users:
                    for uid in vc.joined_users:
                        u = db.query(User).filter(User.id == uid).first()
                        if u:
                            participants.append(u.first_name or u.email)

                if search:
                    haystack = ((channel_name or "") + " " + " ".join(participants)).lower()
                    if search.lower() not in haystack:
                        continue

                entries.append({
                    "id": f"video-{vc.id}",
                    "source_id": vc.id,
                    "call_type": "video",
                    "direction": "internal",
                    "status": vc.status,
                    "started_at": vc.started_at.isoformat() if vc.started_at else None,
                    "ended_at": vc.ended_at.isoformat() if vc.ended_at else None,
                    "duration_seconds": duration_seconds,
                    "title": channel_name or f"Call #{vc.id}",
                    "from_number": None,
                    "to_number": None,
                    "recording_url": None,
                    "recording_duration_secs": None,
                    "full_transcript": None,
                    "csat_score": None,
                    "channel_id": vc.channel_id,
                    "channel_name": channel_name,
                    "event_id": None,
                    "event_title": None,
                    "attendees": None,
                    "participants": participants,
                })

    # ── 3. Calendar meetings with video ───────────────────────────────────────
    if (not call_type or call_type == "meeting") and not show_missed:
        if not direction or direction == "internal":
            q = db.query(CalendarEvent).filter(
                CalendarEvent.company_id == current_user.company_id,
                CalendarEvent.video_enabled == True,
            )
            if search:
                s = f"%{search}%"
                q = q.filter(
                    (CalendarEvent.title.ilike(s)) | (CalendarEvent.description.ilike(s))
                )
            now = datetime.now(timezone.utc)
            for ev in q.order_by(CalendarEvent.start_time.desc()).all():
                if ev.livekit_room_name:
                    ev_status = "active"
                elif ev.end_time.replace(tzinfo=timezone.utc) < now:
                    ev_status = "completed"
                else:
                    ev_status = "scheduled"

                if status and status != ev_status:
                    continue

                duration_seconds = int((ev.end_time - ev.start_time).total_seconds())

                entries.append({
                    "id": f"meeting-{ev.id}",
                    "source_id": ev.id,
                    "call_type": "meeting",
                    "direction": "internal",
                    "status": ev_status,
                    "started_at": ev.start_time.isoformat(),
                    "ended_at": ev.end_time.isoformat(),
                    "duration_seconds": duration_seconds,
                    "title": ev.title,
                    "from_number": None,
                    "to_number": None,
                    "recording_url": None,
                    "recording_duration_secs": None,
                    "full_transcript": None,
                    "csat_score": None,
                    "channel_id": ev.channel_id,
                    "channel_name": None,
                    "event_id": ev.id,
                    "event_title": ev.title,
                    "attendees": ev.attendees or [],
                    "participants": ev.attendees or [],
                    "location": ev.location,
                    "description": ev.description,
                })

    # Sort all entries by started_at descending
    entries.sort(key=lambda x: x["started_at"] or "", reverse=True)

    total = len(entries)
    page = entries[skip: skip + limit]

    return {"entries": page, "total": total, "skip": skip, "limit": limit}
