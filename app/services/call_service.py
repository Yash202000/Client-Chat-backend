"""
Contact-centre call lifecycle (LiveKit SIP): call records, ordered call events, ringing human
agents, answering and ending calls.

Inbound calls are created idempotently from either the LiveKit webhook (API process) or the
voice process, whichever sees the SIP participant first; VoiceCall.call_sid holds the SIP call id.
DB functions are synchronous like the rest of the backend; LiveKit and websocket helpers are async.
"""
import json
import logging
from datetime import datetime, timezone
from typing import Iterable, Optional

from livekit import api
from sqlalchemy import func, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.call_event import CallEvent, CallLeg
from app.models.conversation_session import ConversationSession
from app.models.phone_number import PhoneNumber
from app.models.team_membership import TeamMembership
from app.models.user import User
from app.models.voice_call import VoiceCall, CallStatus
from app.services import contact_service
from app.services.connection_manager import manager

logger = logging.getLogger(__name__)

PROVIDER = "livekit_sip"
ACTIVE_STATUSES = (CallStatus.RINGING.value, CallStatus.IN_PROGRESS.value)
ONLINE_PRESENCE = ("online", "available")


def _now() -> datetime:
    # voice_calls timestamps are naive UTC (existing columns)
    return datetime.utcnow()


def agent_identity(user_id: int) -> str:
    return f"user_{user_id}"


def user_id_from_identity(identity: str) -> Optional[int]:
    if identity.startswith("user_"):
        try:
            return int(identity[5:])
        except ValueError:
            return None
    return None


# ---------------------------------------------------------------- records

def get_or_create_inbound_call(
    db: Session, *, phone: PhoneNumber, room_name: str, sip_call_id: str, caller: str, called: str,
) -> tuple[VoiceCall, bool]:
    """Returns (call, created). Safe to call concurrently from the webhook and the voice process."""
    call = db.query(VoiceCall).filter(VoiceCall.call_sid == sip_call_id).first()
    if call:
        return call, False

    contact = contact_service.get_or_create_contact_for_channel(
        db, company_id=phone.company_id, channel="voice", channel_identifier=caller or "unknown",
    )
    conversation_id = f"voice_{sip_call_id}"
    session = db.query(ConversationSession).filter(ConversationSession.conversation_id == conversation_id).first()
    if not session:
        session = ConversationSession(
            conversation_id=conversation_id,
            company_id=phone.company_id,
            contact_id=contact.id,
            channel="voice",
            agent_id=phone.default_agent_id,
            status="pending_agent_assignment" if phone.routing_mode == "direct" else "active",
            waiting_for_agent=phone.routing_mode == "direct",
            is_ai_enabled=phone.routing_mode != "direct",
        )
        db.add(session)

    call = VoiceCall(
        call_sid=sip_call_id,
        provider=PROVIDER,
        room_name=room_name,
        from_number=caller or "unknown",
        to_number=called or phone.number,
        company_id=phone.company_id,
        phone_number_id=phone.id,
        agent_id=phone.default_agent_id,
        conversation_id=conversation_id,
        contact_id=contact.id,
        status=CallStatus.RINGING.value,
        direction="inbound",
        started_at=_now(),
        call_metadata={"routing_mode": phone.routing_mode},
    )
    db.add(call)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()  # the other process created it first
        return db.query(VoiceCall).filter(VoiceCall.call_sid == sip_call_id).one(), False
    db.refresh(call)
    record_event(db, call, "offer", actor_type="caller", payload={"caller": caller, "called": called, "room": room_name})
    return call, True


def record_event(
    db: Session, call: VoiceCall, type: str, *, actor_type: str = "system",
    actor_user_id: Optional[int] = None, payload: Optional[dict] = None,
) -> CallEvent:
    """Append an event with the next per-call sequence number (row lock on the call keeps order)."""
    db.query(VoiceCall.id).filter(VoiceCall.id == call.id).with_for_update().one()
    seq = (db.query(func.max(CallEvent.seq)).filter(CallEvent.call_id == call.id).scalar() or 0) + 1
    event = CallEvent(call_id=call.id, seq=seq, type=type, actor_type=actor_type,
                      actor_user_id=actor_user_id, payload=payload or {})
    db.add(event)
    db.commit()
    return event


def find_call_by_room(db: Session, room_name: str) -> Optional[VoiceCall]:
    return db.query(VoiceCall).filter(VoiceCall.room_name == room_name).order_by(VoiceCall.id.desc()).first()


def serialize(call: VoiceCall) -> dict:
    contact = call.contact
    return {
        "id": call.id,
        "room": call.room_name,
        "status": call.status,
        "direction": call.direction,
        "caller": call.from_number,
        "called": call.to_number,
        "contact_id": call.contact_id,
        "contact_name": (contact.name if contact else None),
        "conversation_id": call.conversation_id,
        "phone_number_id": call.phone_number_id,
        "handled_by_user_id": call.handled_by_user_id,
        "routing_mode": (call.call_metadata or {}).get("routing_mode"),
        "started_at": call.started_at.isoformat() + "Z" if call.started_at else None,
        "answered_at": call.answered_at.isoformat() + "Z" if call.answered_at else None,
        "ended_at": call.ended_at.isoformat() + "Z" if call.ended_at else None,
        "duration_seconds": call.duration_seconds,
        "talk_seconds": call.talk_seconds,
        "ended_by": call.ended_by,
        "queue_id": call.queue_id,
        "on_hold": call.hold_started_at is not None,
        "hold_seconds": call.hold_seconds or 0,
        "disposition_code_id": call.disposition_code_id,
        "manual_entry": bool(call.manual_entry),
        "recording_status": call.recording_status,
        "consult": bool((call.call_metadata or {}).get("consult")),
    }


# ---------------------------------------------------------------- ringing / answering

def new_call_payloads(db: Session, call: VoiceCall) -> list[dict]:
    """A new call is also a new conversation: events for the call UI and the Calls inbox."""
    payloads = [{"type": "phone_call_new", "call": serialize(call)}]
    session = db.query(ConversationSession).filter(ConversationSession.conversation_id == call.conversation_id).first()
    if session:
        from app.schemas.websocket import WebSocketSessionUpdate
        payloads.append({
            "type": "new_session", "session": WebSocketSessionUpdate.model_validate(session).model_dump(mode="json", by_alias=True),
        })
    return payloads


async def announce_new_call(db: Session, call: VoiceCall) -> None:
    for payload in new_call_payloads(db, call):
        await broadcast(call.company_id, payload)


def ring_targets(db: Session, phone: PhoneNumber, team_id: Optional[int] = None) -> list[int]:
    """Online, active users who should ring: the given team, the number's ring team, or everyone in the company."""
    q = db.query(User.id).filter(
        User.company_id == phone.company_id, User.is_active.is_(True), User.presence_status.in_(ONLINE_PRESENCE),
    )
    team_id = team_id or phone.ring_team_id
    if team_id:
        q = q.join(TeamMembership, TeamMembership.user_id == User.id).filter(TeamMembership.team_id == team_id)
    return [uid for (uid,) in q.distinct().all()]


async def broadcast(company_id: int, payload: dict) -> None:
    await manager.broadcast_to_company(company_id, json.dumps(payload, default=str))


async def ring_agents(db: Session, call: VoiceCall, phone: PhoneNumber, team_id: Optional[int] = None) -> list[int]:
    targets = ring_targets(db, phone, team_id)
    record_event(db, call, "ring", payload={"user_ids": targets})
    await broadcast(call.company_id, {"type": "phone_call_offer", "ring_user_ids": targets, "call": serialize(call)})
    if not targets:
        logger.warning(f"[call {call.id}] no online agents to ring for number {phone.number}")
    return targets


def claim_call(db: Session, call_id: int, company_id: int, user_id: int) -> Optional[VoiceCall]:
    """
    First agent to accept wins (atomic). Claimable: a ringing call, or a call the AI answered that
    is now waiting for a human (handoff). Returns None if already taken or no longer claimable.
    """
    waiting = (db.query(ConversationSession.conversation_id)
               .filter(ConversationSession.waiting_for_agent.is_(True)).scalar_subquery())
    result = db.execute(
        update(VoiceCall)
        .where(VoiceCall.id == call_id, VoiceCall.company_id == company_id,
               VoiceCall.handled_by_user_id.is_(None),
               (VoiceCall.status == CallStatus.RINGING.value)
               | ((VoiceCall.status == CallStatus.IN_PROGRESS.value) & VoiceCall.conversation_id.in_(waiting)))
        .values(handled_by_user_id=user_id)
        .execution_options(synchronize_session=False)
    )
    db.commit()
    if result.rowcount != 1:
        return None
    call = db.query(VoiceCall).filter(VoiceCall.id == call_id).one()
    if call.conversation_id:
        db.query(ConversationSession).filter(ConversationSession.conversation_id == call.conversation_id).update({
            "assignee_id": user_id, "status": "assigned", "waiting_for_agent": False,
            "is_ai_enabled": False, "handoff_accepted_at": _now(),
        })
        db.commit()
    record_event(db, call, "accept", actor_type="agent", actor_user_id=user_id)
    return call


def display_name(user) -> str:
    """Works for both the ORM User and the pydantic user returned by auth dependencies."""
    parts = [getattr(user, "first_name", None), getattr(user, "last_name", None)]
    return " ".join(p for p in parts if p) or user.email


def agent_token(room_name: str, user) -> str:
    return (
        api.AccessToken(settings.LIVEKIT_API_KEY, settings.LIVEKIT_API_SECRET)
        .with_identity(agent_identity(user.id))
        .with_name(display_name(user))
        .with_attributes({"agentconnect.role": "agent", "agentconnect.user_id": str(user.id)})
        .with_grants(api.VideoGrants(room_join=True, room=room_name, can_publish=True,
                                     can_subscribe=True, can_publish_data=True))
        .to_jwt()
    )


def _lock(db: Session, call: VoiceCall) -> VoiceCall:
    """Re-read the call under a row lock: the webhook (API) and the voice process update calls concurrently."""
    return (db.query(VoiceCall).filter(VoiceCall.id == call.id)
            .with_for_update().populate_existing().one())


def mark_answered(db: Session, call: VoiceCall, user_id: Optional[int], actor_type: str = "agent") -> None:
    call = _lock(db, call)
    if call.answered_at is not None or call.status != CallStatus.RINGING.value:
        db.commit()  # release the lock
        return
    call.answered_at = _now()
    call.status = CallStatus.IN_PROGRESS.value
    db.commit()
    record_event(db, call, "answer", actor_type=actor_type, actor_user_id=user_id)


async def route_to_agents(db: Session, call: VoiceCall, phone: Optional[PhoneNumber],
                         queue_id: Optional[int] = None, team_id: Optional[int] = None) -> dict:
    """Queue the call for ACD (queue given, or the number's queue); otherwise ring a team / everyone online."""
    from app.models.contact_center import CallQueue
    from app.services import acd_service

    queue_id = queue_id or (phone.queue_id if phone else None)
    queue = db.query(CallQueue).filter(CallQueue.id == queue_id, CallQueue.company_id == call.company_id).first() if queue_id else None
    if queue:
        acd_service.enqueue(db, call, queue)
        await broadcast(call.company_id, {"type": "phone_call_queued", "call": serialize(call),
                                          "queue": {"id": queue.id, "name": queue.name}})
        await acd_service.dispatch(db, call.company_id)
        return {"queued": True, "queue_id": queue.id, "max_wait_seconds": queue.max_wait_seconds,
                "overflow_text": queue.overflow_text}
    targets = await ring_agents(db, call, phone, team_id=team_id) if phone else []
    return {"queued": False, "agents_ringing": len(targets)}


async def request_human(db: Session, conversation_id: str, reason: str = "",
                        team_id: Optional[int] = None, queue_id: Optional[int] = None) -> Optional[dict]:
    """
    AI -> human handoff on a phone call: the AI stops answering and the number's agents ring.
    The voice process keeps the caller company until an agent joins (or gives the call back to the AI).
    """
    call = (db.query(VoiceCall).filter(VoiceCall.conversation_id == conversation_id)
            .order_by(VoiceCall.id.desc()).first())
    if not call or call.status not in ACTIVE_STATUSES:
        return None
    session = db.query(ConversationSession).filter(ConversationSession.conversation_id == conversation_id).first()
    if session:
        session.waiting_for_agent = True
        session.is_ai_enabled = False
        session.status = "pending_agent_assignment"
        session.handoff_requested_at = _now()
        session.handoff_reason = reason or "caller asked for a human"
        db.commit()
    record_event(db, call, "handoff_requested", actor_type="ai", payload={"reason": reason})
    phone = db.query(PhoneNumber).filter(PhoneNumber.id == call.phone_number_id).first()
    routed = await route_to_agents(db, call, phone, queue_id=queue_id, team_id=team_id)
    return {"status": "voice_handoff_requested", **routed}


def give_back_to_ai(db: Session, call: VoiceCall) -> None:
    """Nobody answered the handoff: the AI resumes the conversation."""
    session = db.query(ConversationSession).filter(ConversationSession.conversation_id == call.conversation_id).first()
    if session and session.waiting_for_agent:
        session.waiting_for_agent = False
        session.is_ai_enabled = True
        session.status = "active"
        db.commit()
        record_event(db, call, "handoff_unanswered", actor_type="system")


# ---------------------------------------------------------------- ending

def finish_call(db: Session, call: VoiceCall, ended_by: str, actor_user_id: Optional[int] = None) -> bool:
    """Close the record once (row lock makes this safe across processes). Returns False if already ended."""
    call = _lock(db, call)
    if call.status not in ACTIVE_STATUSES:
        db.commit()  # release the lock
        return False
    now = _now()
    if call.hold_started_at:  # call ended while on hold
        call.hold_seconds = (call.hold_seconds or 0) + (now - call.hold_started_at).total_seconds()
        call.hold_started_at = None
    call.ended_at = now
    call.ended_by = ended_by
    call.duration_seconds = (now - call.started_at).total_seconds() if call.started_at else None
    if call.answered_at:
        call.status = CallStatus.COMPLETED.value
        call.talk_seconds = max((now - call.answered_at).total_seconds() - (call.hold_seconds or 0), 0)
    else:
        call.status = CallStatus.NO_ANSWER.value
    db.commit()
    record_event(db, call, "end", actor_type=ended_by if ended_by in ("caller", "agent") else "system",
                 actor_user_id=actor_user_id, payload={"status": call.status})
    close_legs(db, call, {"caller": "caller_hung_up", "agent": "hung_up"}.get(ended_by, "call_ended"))
    from app.services import recording_service
    recording_service.on_call_ended(db, call)
    if call.direction == "outbound":
        from app.services import outbound_service
        outbound_service.finish_attempt(db, call)
    else:
        from app.services import missed_call_service
        missed_call_service.classify(db, call)
    if call.conversation_id:
        session = db.query(ConversationSession).filter(ConversationSession.conversation_id == call.conversation_id).first()
        if session and session.status not in ("resolved", "archived"):
            session.waiting_for_agent = False
            if call.status == CallStatus.NO_ANSWER.value:
                session.status = "pending"  # missed call stays open for follow-up (M5 adds callback tasks)
            db.commit()
    return True


async def hang_up_room(room_name: Optional[str]) -> None:
    """Deleting the room disconnects everyone, which sends SIP BYE to the caller."""
    if not room_name:
        return
    from app.services.livekit_sip_service import _api
    lk = _api()
    try:
        await lk.room.delete_room(api.DeleteRoomRequest(room=room_name))
    except api.TwirpError as e:
        if e.code != "not_found":
            logger.warning(f"[call] could not delete room {room_name}: {e.message}")
    finally:
        await lk.aclose()


async def end_call(db: Session, call: VoiceCall, ended_by: str, actor_user_id: Optional[int] = None,
                   hang_up: bool = True) -> None:
    if finish_call(db, call, ended_by, actor_user_id):
        await broadcast(call.company_id, {"type": "phone_call_ended", "call": serialize(call)})
        from app.services import acd_service
        await acd_service.on_call_ended(db, call)
    if hang_up:
        await hang_up_room(call.room_name)


def active_calls(db: Session, company_id: int, user_ids: Optional[Iterable[int]] = None) -> list[VoiceCall]:
    q = db.query(VoiceCall).filter(VoiceCall.company_id == company_id, VoiceCall.provider == PROVIDER,
                                   VoiceCall.status.in_(ACTIVE_STATUSES))
    if user_ids is not None:
        q = q.filter(VoiceCall.handled_by_user_id.in_(list(user_ids)))
    return q.order_by(VoiceCall.started_at.desc()).all()


# ---------------------------------------------------------------- hold (FR-CC-016)

def set_hold(db: Session, call: VoiceCall, on_hold: bool, user_id: int) -> VoiceCall:
    """Hold time is tracked separately from talk time (talk = answered..ended minus hold)."""
    call = _lock(db, call)
    now = _now()
    if on_hold and call.hold_started_at is None and call.status == CallStatus.IN_PROGRESS.value:
        call.hold_started_at = now
        db.commit()
        record_event(db, call, "hold", actor_type="agent", actor_user_id=user_id)
    elif not on_hold and call.hold_started_at is not None:
        call.hold_seconds = (call.hold_seconds or 0) + (now - call.hold_started_at).total_seconds()
        call.hold_started_at = None
        db.commit()
        record_event(db, call, "resume", actor_type="agent", actor_user_id=user_id)
    else:
        db.commit()  # release the lock
    return call


# ---------------------------------------------------------------- transfer chain (FR-CC-028)

def open_leg(db: Session, call: VoiceCall, kind: str, user_id: Optional[int] = None, party: Optional[str] = None) -> CallLeg:
    db.query(VoiceCall.id).filter(VoiceCall.id == call.id).with_for_update().one()
    existing = (db.query(CallLeg).filter(CallLeg.call_id == call.id, CallLeg.kind == kind, CallLeg.ended_at.is_(None),
                                         CallLeg.user_id.is_(None) if user_id is None else CallLeg.user_id == user_id).first())
    if existing:
        db.commit()
        return existing
    seq = (db.query(func.max(CallLeg.seq)).filter(CallLeg.call_id == call.id).scalar() or 0) + 1
    leg = CallLeg(call_id=call.id, seq=seq, kind=kind, user_id=user_id, party=party, started_at=datetime.now(timezone.utc))
    db.add(leg)
    db.commit()
    return leg


def close_legs(db: Session, call: VoiceCall, end_reason: str, *, kind: Optional[str] = None, user_id: Optional[int] = None,
               transferred_to: Optional[str] = None) -> None:
    q = db.query(CallLeg).filter(CallLeg.call_id == call.id, CallLeg.ended_at.is_(None))
    if kind:
        q = q.filter(CallLeg.kind == kind)
    if user_id is not None:
        q = q.filter(CallLeg.user_id == user_id)
    for leg in q.all():
        leg.ended_at = datetime.now(timezone.utc)
        leg.end_reason = leg.end_reason or end_reason
        if transferred_to:
            leg.transferred_to = transferred_to
    db.commit()


def legs(db: Session, call: VoiceCall) -> list[dict]:
    out = []
    for leg in db.query(CallLeg).filter(CallLeg.call_id == call.id).order_by(CallLeg.seq).all():
        duration = (leg.ended_at - leg.started_at).total_seconds() if leg.ended_at else None
        out.append({"seq": leg.seq, "kind": leg.kind, "user_id": leg.user_id, "party": leg.party,
                    "started_at": leg.started_at.isoformat(), "ended_at": leg.ended_at.isoformat() if leg.ended_at else None,
                    "duration_seconds": duration, "end_reason": leg.end_reason, "transferred_to": leg.transferred_to})
    return out
