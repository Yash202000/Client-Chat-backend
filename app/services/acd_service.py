"""
Automatic call distribution (ACD) for contact-centre calls, plus agent states.

Calls wait in a CallQueue as CallQueueEntry rows (status "waiting"). A dispatcher offers each
waiting call to ONE eligible agent at a time (longest idle first, lower tier first); the offer
times out after queue.offer_timeout_seconds and moves to the next agent. Eligible = queue member,
state "ready", online, active, on shift (if the agent has shifts), has the queue's skill, and not
already being offered another call. Accepting goes through call_service.claim_call.

Agent states (FR-CC-046/047/048): every change closes the previous AgentStateHistory row. Calls
drive states automatically: offer accepted -> on_call, call ended -> wrap_up -> ready after the
queue's wrap-up time (or when the agent saves the wrap-up).
"""
import asyncio
import json
import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app.models.call_queue import CallQueueEntry
from app.models.contact_center import (
    AgentReasonCode, AgentState, AgentStateHistory, CallQueue, CallQueueMember, NOT_READY_STATES, AGENT_STATES,
    Shift, ShiftAssignment,
)
from app.models.user import User
from app.models.voice_call import VoiceCall

logger = logging.getLogger(__name__)

ONLINE_PRESENCE = ("online", "available", "busy", "in_call")
WAITING = "waiting"


def _utc() -> datetime:
    return datetime.now(timezone.utc)


def _naive(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt


class StateError(ValueError):
    pass


# ---------------------------------------------------------------- agent states

def get_state(db: Session, user_id: int, company_id: int) -> AgentState:
    row = db.query(AgentState).filter(AgentState.user_id == user_id).first()
    if not row:
        row = AgentState(user_id=user_id, company_id=company_id, state="logged_out", since=_utc())
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def serialize_state(row: AgentState) -> dict:
    return {
        "user_id": row.user_id,
        "state": row.state,
        "reason_code_id": row.reason_code_id,
        "reason": row.reason_code.name if row.reason_code else None,
        "since": row.since.isoformat() if row.since else None,
        "current_call_id": row.current_call_id,
    }


def set_state(db: Session, user_id: int, company_id: int, state: str, *, reason_code_id: Optional[int] = None,
              source: str = "manual", changed_by: Optional[int] = None, call_id: Optional[int] = None,
              role_id: Optional[int] = None) -> AgentState:
    if state not in AGENT_STATES:
        raise StateError(f"Unknown state '{state}'")
    if source == "manual" and state in ("on_call", "wrap_up"):
        raise StateError("On call and wrap-up are set by calls, not manually")
    if state in NOT_READY_STATES and source == "manual":
        if not reason_code_id:
            raise StateError("A reason is required for this status")
        code = db.query(AgentReasonCode).filter(AgentReasonCode.id == reason_code_id,
                                                AgentReasonCode.company_id == company_id,
                                                AgentReasonCode.is_active.is_(True)).first()
        if not code:
            raise StateError("Unknown reason code")
        if code.allowed_role_ids and role_id not in code.allowed_role_ids:
            raise StateError("This reason is not available for your role")
        state = code.state  # the code decides which not-ready state it is
    else:
        reason_code_id = None

    row = get_state(db, user_id, company_id)
    if row.state == "on_call" and source == "manual" and state != "logged_out":
        raise StateError("You are on a call; your status changes when the call ends")  # FR-CC-048: no conflicts
    now = _utc()
    open_hist = (db.query(AgentStateHistory).filter(AgentStateHistory.user_id == user_id,
                                                    AgentStateHistory.ended_at.is_(None))
                 .order_by(AgentStateHistory.id.desc()).all())
    for h in open_hist:
        h.ended_at = now
    db.add(AgentStateHistory(user_id=user_id, company_id=company_id, state=state, reason_code_id=reason_code_id,
                             started_at=now, changed_by_user_id=changed_by, source=source))
    row.state, row.reason_code_id, row.since = state, reason_code_id, now
    if state == "on_call":
        row.current_call_id = call_id
    elif state == "wrap_up":
        row.last_call_ended_at = now  # keeps current_call_id: the call being wrapped up
    else:
        row.current_call_id = None
    db.commit()
    db.refresh(row)
    return row


async def broadcast_state(company_id: int, row: AgentState) -> None:
    from app.services.call_service import broadcast
    await broadcast(company_id, {"type": "agent_state", "agent": serialize_state(row)})


# ---------------------------------------------------------------- shifts

def on_shift(db: Session, user_id: int, now: Optional[datetime] = None) -> bool:
    """Agents without any shift assignment are always eligible; otherwise one of their shifts must be active now."""
    shifts = (db.query(Shift).join(ShiftAssignment, ShiftAssignment.shift_id == Shift.id)
              .filter(ShiftAssignment.user_id == user_id).all())
    if not shifts:
        return True
    now = now or _utc()
    for shift in shifts:
        if not shift.is_active:
            continue
        try:
            local = now.astimezone(ZoneInfo(shift.timezone or "UTC"))
        except Exception:
            local = now
        hhmm = local.strftime("%H:%M")
        for slot in shift.schedule or []:
            if local.weekday() in [int(d) for d in slot.get("days", [])] and slot.get("start", "00:00") <= hhmm < slot.get("end", "24:00"):
                return True
    return False


# ---------------------------------------------------------------- queueing

def enqueue(db: Session, call: VoiceCall, queue: Optional[CallQueue], priority: int = 0,
            extra: Optional[dict] = None) -> CallQueueEntry:
    from app.services import call_service

    entry = db.query(CallQueueEntry).filter(CallQueueEntry.voice_call_id == call.id,
                                            CallQueueEntry.status == WAITING).first()
    if entry:
        return entry
    entry = CallQueueEntry(
        company_id=call.company_id, call_sid=call.call_sid, source="livekit_sip",
        caller_number=call.from_number, caller_name=call.contact.name if call.contact else None,
        session_id=call.conversation_id, contact_id=call.contact_id, status=WAITING,
        priority=(queue.priority * 10 if queue else 50) + priority, required_skill=queue.required_skill if queue else None,
        queue_id=queue.id if queue else None, voice_call_id=call.id, declined_user_ids=[], entered_at=datetime.utcnow(),
        extra=extra or None,
    )
    db.add(entry)
    if queue:
        call.queue_id = queue.id
    db.commit()
    db.refresh(entry)
    call_service.record_event(db, call, "queue", payload={"queue_id": queue.id if queue else None,
                                                         "queue": queue.name if queue else None, **(extra or {})})
    return entry


def eligible_agents(db: Session, queue: CallQueue, exclude: list[int]) -> list[int]:
    busy = {uid for (uid,) in db.query(CallQueueEntry.offered_to_user_id)
            .filter(CallQueueEntry.status == WAITING, CallQueueEntry.offered_to_user_id.isnot(None)).all()}
    rows = (db.query(CallQueueMember.user_id, CallQueueMember.tier, AgentState.last_call_ended_at, User.skills)
            .join(AgentState, AgentState.user_id == CallQueueMember.user_id)
            .join(User, User.id == CallQueueMember.user_id)
            .filter(CallQueueMember.queue_id == queue.id, AgentState.state == "ready",
                    User.is_active.is_(True), User.presence_status.in_(ONLINE_PRESENCE))
            .all())
    candidates = []
    for user_id, tier, idle_since, skills in rows:
        if user_id in exclude or user_id in busy:
            continue
        if queue.required_skill and queue.required_skill not in (skills or []):
            continue
        if not on_shift(db, user_id):
            continue
        candidates.append((tier, idle_since or datetime.min.replace(tzinfo=timezone.utc), user_id))
    return [uid for _, _, uid in sorted(candidates)]


DEFAULT_HANDLE_SECONDS = 180  # until the queue has enough answered calls to average
SERVING_STATES = ("ready", "on_call", "wrap_up")


def wait_estimate(db: Session, call_id: int) -> Optional[dict]:
    """
    FR-CC-013: position and expected wait of a call waiting in a queue that announces wait times.
    expected wait = position x average handling time (last 7 days: talk + hold + wrap-up) / agents serving
    the queue (ready, on a call or in wrap-up). None if the call isn't waiting or the queue doesn't announce.
    """
    entry = db.query(CallQueueEntry).filter(CallQueueEntry.voice_call_id == call_id, CallQueueEntry.status == WAITING).first()
    if not entry or not entry.queue_id:
        return None
    queue = db.query(CallQueue).filter(CallQueue.id == entry.queue_id).first()
    if not queue or not queue.announce_wait_time:
        return None
    ahead = (db.query(func.count(CallQueueEntry.id))
             .filter(CallQueueEntry.queue_id == queue.id, CallQueueEntry.status == WAITING, CallQueueEntry.id != entry.id,
                     or_(CallQueueEntry.priority > entry.priority,
                         and_(CallQueueEntry.priority == entry.priority, CallQueueEntry.entered_at <= entry.entered_at)))
             .scalar() or 0)
    since = datetime.utcnow() - timedelta(days=7)
    handled = (db.query(func.avg(func.coalesce(VoiceCall.talk_seconds, 0) + func.coalesce(VoiceCall.hold_seconds, 0)
                                 + func.coalesce(VoiceCall.wrap_up_seconds, 0)), func.count(VoiceCall.id))
               .filter(VoiceCall.queue_id == queue.id, VoiceCall.answered_at.isnot(None), VoiceCall.ended_at >= since)
               .one())
    average = float(handled[0]) if handled[1] and handled[1] >= 3 and handled[0] else DEFAULT_HANDLE_SECONDS
    agents = (db.query(func.count(CallQueueMember.user_id))
              .join(AgentState, AgentState.user_id == CallQueueMember.user_id)
              .join(User, User.id == CallQueueMember.user_id)
              .filter(CallQueueMember.queue_id == queue.id, AgentState.state.in_(SERVING_STATES), User.is_active.is_(True))
              .scalar() or 0)
    position = ahead + 1
    seconds = position * average / max(agents, 1)
    return {"position": position, "minutes": max(1, math.ceil(seconds / 60)), "agents": agents,
            "average_handle_seconds": round(average), "interval": queue.announce_interval_seconds, "queue_id": queue.id}


def _minutes_ar(m: int) -> str:
    if m == 1:
        return "دقيقة واحدة"
    if m == 2:
        return "دقيقتين"
    return f"{m} دقائق" if m <= 10 else f"{m} دقيقة"


def wait_message(estimate: dict, language: str = "en") -> str:
    n, m = estimate["position"], estimate["minutes"]
    if (language or "en").split("-")[0].lower() == "ar":
        return f"ترتيبك في قائمة الانتظار هو {n}. وقت الانتظار المتوقع حوالي {_minutes_ar(m)}. شكراً لانتظارك."
    minutes = "one minute" if m == 1 else f"{m} minutes"
    return f"You are number {n} in the queue. Your expected waiting time is about {minutes}. Thank you for waiting."


async def dispatch(db: Session, company_id: Optional[int] = None) -> int:
    """Offer waiting calls to agents; expire unanswered offers. Returns the number of new offers."""
    from app.services import call_service

    now = datetime.utcnow()
    q = db.query(CallQueueEntry).filter(CallQueueEntry.status == WAITING, CallQueueEntry.source == "livekit_sip",
                                        CallQueueEntry.voice_call_id.isnot(None))
    if company_id:
        q = q.filter(CallQueueEntry.company_id == company_id)
    offers = 0
    for entry in q.order_by(CallQueueEntry.priority.desc(), CallQueueEntry.entered_at).all():
        call = db.query(VoiceCall).filter(VoiceCall.id == entry.voice_call_id).first()
        if not call or call.status not in call_service.ACTIVE_STATUSES:
            entry.status = "abandoned"
            entry.ended_at = now
            db.commit()
            continue
        if entry.offered_to_user_id:
            if entry.offer_expires_at and entry.offer_expires_at > now:
                continue  # offer still ringing
            # unanswered offer: move on to the next agent
            missed = entry.offered_to_user_id
            entry.declined_user_ids = list(entry.declined_user_ids or []) + [missed]
            entry.offered_to_user_id, entry.offer_expires_at = None, None
            db.commit()
            call_service.record_event(db, call, "offer_timeout", actor_type="agent", actor_user_id=missed)
            await call_service.broadcast(call.company_id, {"type": "phone_call_offer_withdrawn",
                                                           "call": call_service.serialize(call), "user_id": missed})
        queue = db.query(CallQueue).filter(CallQueue.id == entry.queue_id).first() if entry.queue_id else None
        target = _transfer_target(db, entry, call)
        if target is not None:
            candidates = [target]
        elif not queue:
            continue  # nobody left to offer to; the caller stays on hold until someone picks it up
        else:
            candidates = eligible_agents(db, queue, exclude=list(entry.declined_user_ids or []))
        if not candidates and entry.declined_user_ids and queue:
            # everyone has had a turn: start a new round
            entry.declined_user_ids = []
            db.commit()
            candidates = eligible_agents(db, queue, exclude=[])
        if not candidates:
            continue
        user_id = candidates[0]
        offer_timeout = queue.offer_timeout_seconds if queue else 20
        entry.offered_to_user_id = user_id
        entry.offer_expires_at = now + timedelta(seconds=offer_timeout)
        entry.offer_attempts = (entry.offer_attempts or 0) + 1
        entry.ringing_at = now
        db.commit()
        extra = entry.extra or {}
        call_service.record_event(db, call, "offer", actor_type="system",
                                  payload={"user_id": user_id, "queue_id": queue.id if queue else None,
                                           "transfer": bool(extra.get("transfer"))})
        await call_service.broadcast(call.company_id, {
            "type": "phone_call_offer", "ring_user_ids": [user_id], "call": call_service.serialize(call),
            "queue": {"id": queue.id, "name": queue.name} if queue else None, "offer_timeout_seconds": offer_timeout,
            "transfer": {"from_user_id": extra.get("from_user_id"), "note": extra.get("note")} if extra.get("transfer") else None,
        })
        offers += 1
    return offers


def _transfer_target(db: Session, entry: CallQueueEntry, call: VoiceCall) -> Optional[int]:
    """
    Transfer to a specific agent: offer to them first. If they don't take it (FR-CC-026) the call goes
    back to the queue, or — when there is no queue — back to the agent who transferred it.
    """
    from app.services import call_service

    extra = dict(entry.extra or {})
    declined = set(entry.declined_user_ids or [])
    target, origin = extra.get("target_user_id"), extra.get("from_user_id")
    if target and target not in declined:
        return target
    if target and target in declined and not extra.get("transfer_failed"):
        extra["transfer_failed"] = True
        entry.extra = extra
        db.commit()
        call_service.record_event(db, call, "transfer_failed", actor_type="system",
                                  payload={"target_user_id": target, "returned_to": "queue" if entry.queue_id else "agent"})
    if not entry.queue_id and origin and origin not in declined:
        return origin
    return None


async def expire_wrap_ups(db: Session) -> None:
    """Agents whose wrap-up time ran out become ready again."""
    rows = db.query(AgentState).filter(AgentState.state == "wrap_up").all()
    for row in rows:
        call = db.query(VoiceCall).filter(VoiceCall.id == row.current_call_id).first() if row.current_call_id else None
        queue = db.query(CallQueue).filter(CallQueue.id == call.queue_id).first() if call and call.queue_id else None
        wrap = queue.wrap_up_seconds if queue else 30
        if row.since and _utc() - row.since >= timedelta(seconds=wrap):
            if call and call.wrap_up_seconds is None:
                call.wrap_up_seconds = float(wrap)
                db.commit()
            row = set_state(db, row.user_id, row.company_id, "ready", source="system")
            await broadcast_state(row.company_id, row)


# ---------------------------------------------------------------- call lifecycle hooks

async def on_accepted(db: Session, call: VoiceCall, user_id: int) -> None:
    entry = db.query(CallQueueEntry).filter(CallQueueEntry.voice_call_id == call.id, CallQueueEntry.status == WAITING).first()
    if entry:
        entry.status = "connected"
        entry.connected_at = datetime.utcnow()
        entry.assigned_agent_id = user_id
        entry.offered_to_user_id = None
        db.commit()
    row = set_state(db, user_id, call.company_id, "on_call", source="call", call_id=call.id)
    await broadcast_state(call.company_id, row)


def on_declined(db: Session, call: VoiceCall, user_id: int) -> None:
    entry = db.query(CallQueueEntry).filter(CallQueueEntry.voice_call_id == call.id, CallQueueEntry.status == WAITING).first()
    if entry and entry.offered_to_user_id == user_id:
        entry.declined_user_ids = list(entry.declined_user_ids or []) + [user_id]
        entry.offered_to_user_id, entry.offer_expires_at = None, None
        db.commit()


async def on_call_ended(db: Session, call: VoiceCall) -> None:
    now = datetime.utcnow()
    entry = db.query(CallQueueEntry).filter(CallQueueEntry.voice_call_id == call.id, CallQueueEntry.status == WAITING).first()
    if entry:
        entry.status = "abandoned"
        entry.ended_at = now
        entry.extra = {**(entry.extra or {}), "loss_reason": "caller_hung_up_in_queue"}
        db.commit()
    connected = db.query(CallQueueEntry).filter(CallQueueEntry.voice_call_id == call.id, CallQueueEntry.status == "connected").first()
    if connected:
        connected.ended_at = now
        db.commit()
    if call.handled_by_user_id:
        row = get_state(db, call.handled_by_user_id, call.company_id)
        if row.state == "on_call" and row.current_call_id == call.id:
            row = set_state(db, call.handled_by_user_id, call.company_id, "wrap_up", source="call")
            await broadcast_state(call.company_id, row)


async def complete_wrap_up(db: Session, call: VoiceCall, user_id: int, disposition_code_id: Optional[int],
                           note: Optional[str]) -> AgentState:
    from app.models.contact_center import DispositionCode
    from app.services import call_service

    if disposition_code_id:
        code = db.query(DispositionCode).filter(DispositionCode.id == disposition_code_id,
                                                DispositionCode.company_id == call.company_id).first()
        if not code:
            raise StateError("Unknown disposition code")
        if code.requires_note and not (note or "").strip():
            raise StateError(f"A note is required for '{code.name}'")
    call.disposition_code_id = disposition_code_id
    call.disposition_note = note
    row = get_state(db, user_id, call.company_id)
    if row.state == "wrap_up" and call.wrap_up_seconds is None and row.since:
        call.wrap_up_seconds = (_utc() - row.since).total_seconds()
    db.commit()
    call_service.record_event(db, call, "wrap_up", actor_type="agent", actor_user_id=user_id,
                              payload={"disposition_code_id": disposition_code_id})
    if row.state == "wrap_up":
        row = set_state(db, user_id, call.company_id, "ready", source="call")
        await broadcast_state(call.company_id, row)
    return row


# ---------------------------------------------------------------- background loop

async def run_dispatcher(interval: float = 1.0) -> None:
    """Background task in the API process. With Redis, a short lock ensures one dispatcher across workers."""
    from app.core.config import settings
    from app.core.database import SessionLocal

    from app.core.redis_client import async_redis, redis_enabled

    redis = async_redis() if redis_enabled() else None
    while True:
        try:
            if redis is None or await redis.set("agentconnect:acd:lock", "1", nx=True, px=int(interval * 1500)):
                db = SessionLocal()
                try:
                    await dispatch(db)
                    await expire_wrap_ups(db)
                finally:
                    db.close()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("[acd] dispatcher tick failed")
        await asyncio.sleep(interval)
