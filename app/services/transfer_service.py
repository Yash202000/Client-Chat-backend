"""
Call transfers, consultation and supervision for contact-centre calls (M4).

Blind transfer (FR-CC-021/023/024/025/026/027): the transferring agent leaves; the caller waits
(the voice process keeps them company in "hold" mode when available) while the call is offered to
the target agent / queue through the ACD. A failed agent transfer falls back to the queue, or to
the transferring agent. External numbers are allowed only if the directory marks them transferable.

Consultation / warm transfer (FR-CC-022/030): the caller is put on hold; the agent and the target
talk in a separate consult room; then the agent completes (target joins the call, agent leaves)
or cancels (consult room closed, agent resumes).

Supervision (FR-CC-049): listen / whisper / barge tokens for supervisors; every use is audited.
"""
import json
import logging
import secrets
from typing import Optional

from livekit import api
from sqlalchemy.orm import Session

from app.core.audit import log_action
from app.core.config import settings
from app.models.contact_center import CallQueue, DirectoryEntry
from app.models.conversation_session import ConversationSession
from app.models.phone_number import PhoneNumber
from app.models.user import User
from app.models.voice_call import VoiceCall
from app.services import acd_service, call_service, livekit_nodes, recording_service

logger = logging.getLogger(__name__)


class TransferError(ValueError):
    pass


def _lk() -> api.LiveKitAPI:
    from app.services.livekit_sip_service import _api
    return _api()


def _user_name(user) -> str:
    return call_service.display_name(user)


def _save_note(db: Session, call: VoiceCall, user_id: int, text: str) -> None:
    """Context continuity (FR-CC-027): a note the receiving agent sees in the conversation."""
    if not text or not call.conversation_id:
        return
    from app.schemas.chat_message import ChatMessageCreate
    from app.services import chat_service
    chat_service.create_chat_message(db, ChatMessageCreate(message=text, message_type="note"), None,
                                     call.conversation_id, call.company_id, "agent", assignee_id=user_id)


async def _keep_caller_company(call: VoiceCall) -> None:
    """Dispatch the voice process in hold mode so the caller isn't left in silence while waiting."""
    lk = _lk()
    try:
        await lk.agent_dispatch.create_dispatch(api.CreateAgentDispatchRequest(
            agent_name=settings.TELEPHONY_VOICE_AGENT_NAME, room=call.room_name,
            metadata=json.dumps({"mode": "hold", "call_id": call.id, "phone_number_id": call.phone_number_id,
                                 "company_id": call.company_id})))
    except Exception as e:  # no voice process running (direct-only setup): the caller just waits
        logger.info(f"[transfer] hold voice not dispatched for call {call.id}: {e}")
    finally:
        await lk.aclose()


def _release_handler(db: Session, call: VoiceCall, from_user_id: int) -> None:
    """The transferring agent hands the call over: they leave without ending it."""
    call.handled_by_user_id = None
    session = db.query(ConversationSession).filter(ConversationSession.conversation_id == call.conversation_id).first()
    if session:
        session.assignee_id = None
        session.waiting_for_agent = True
        session.status = "pending_agent_assignment"
    db.commit()


async def _agent_after_transfer(db: Session, call: VoiceCall, user_id: int) -> None:
    row = acd_service.get_state(db, user_id, call.company_id)
    if row.state == "on_call":
        row = acd_service.set_state(db, user_id, call.company_id, "wrap_up", source="call")
        await acd_service.broadcast_state(call.company_id, row)


# ---------------------------------------------------------------- blind transfer

async def blind_transfer(db: Session, call: VoiceCall, by_user, *, target_type: str, target_id: Optional[int] = None,
                         number: Optional[str] = None, note: str = "") -> dict:
    if call.status not in call_service.ACTIVE_STATUSES:
        raise TransferError("The call has ended")
    if call.handled_by_user_id != by_user.id:
        raise TransferError("Only the agent on the call can transfer it")

    if target_type == "external":
        return await _external_transfer(db, call, by_user, number=number, entry_id=target_id, note=note)

    queue: Optional[CallQueue] = None
    extra = {"transfer": True, "from_user_id": by_user.id, "note": note or None}
    if target_type == "queue":
        queue = db.query(CallQueue).filter(CallQueue.id == target_id, CallQueue.company_id == call.company_id).first()
        if not queue:
            raise TransferError("Queue not found")
        if not queue.is_open:
            raise TransferError(f"Queue '{queue.name}' is closed")  # FR-CC-023
        label = f"queue:{queue.name}"
    elif target_type == "agent":
        target = db.query(User).filter(User.id == target_id, User.company_id == call.company_id, User.is_active.is_(True)).first()
        if not target or target.id == by_user.id:
            raise TransferError("Choose another agent")
        extra["target_user_id"] = target.id
        # if the agent doesn't answer, the call returns to the queue it came from (or this agent)
        queue = db.query(CallQueue).filter(CallQueue.id == call.queue_id).first() if call.queue_id else None
        label = f"agent:{_user_name(target)}"
    else:
        raise TransferError("Unknown transfer target")

    call_service.record_event(db, call, "transfer", actor_type="agent", actor_user_id=by_user.id,
                              payload={"type": "blind", "to": label, "note": note or None})
    call_service.close_legs(db, call, "transferred", kind="agent", user_id=by_user.id, transferred_to=label)
    _save_note(db, call, by_user.id, f"Transferred to {label}" + (f": {note}" if note else ""))
    _release_handler(db, call, by_user.id)
    acd_service.enqueue(db, call, queue, priority=5, extra=extra)
    log_action(db, call.company_id, by_user.id, "call.transferred", entity_type="voice_call", entity_id=call.id,
               changes={"to": label})
    db.commit()
    await recording_service.resume_if_paused(db, call, "transfer")
    await _agent_after_transfer(db, call, by_user.id)
    await _keep_caller_company(call)
    await call_service.broadcast(call.company_id, {"type": "phone_call_transferred", "call": call_service.serialize(call),
                                                   "from_user_id": by_user.id, "to": label})
    await acd_service.dispatch(db, call.company_id)
    return {"transferred_to": label}


def check_external_number(db: Session, company_id: int, number: str) -> DirectoryEntry:
    """Only directory numbers marked transferable may receive transfers (19991 is read out, never transferred)."""
    entry = db.query(DirectoryEntry).filter(DirectoryEntry.company_id == company_id, DirectoryEntry.number == number).first()
    if not entry or not entry.transfer_allowed:
        raise TransferError(f"Transfers to {number} are not allowed")
    return entry


async def _external_transfer(db: Session, call: VoiceCall, by_user, *, number: Optional[str], entry_id: Optional[int],
                             note: str) -> dict:
    if entry_id:
        entry = db.query(DirectoryEntry).filter(DirectoryEntry.id == entry_id, DirectoryEntry.company_id == call.company_id).first()
        if not entry or not entry.transfer_allowed:
            raise TransferError("Transfers to this number are not allowed")
    else:
        entry = check_external_number(db, call.company_id, (number or "").strip())
    destination = entry.number if entry.number.startswith(("sip:", "tel:")) else f"tel:{entry.number}"
    lk = _lk()
    try:
        participants = await lk.room.list_participants(api.ListParticipantsRequest(room=call.room_name))
        sip = next((p for p in participants.participants if p.kind == api.ParticipantInfo.Kind.SIP), None)
        if not sip:
            raise TransferError("The caller is no longer connected")
        # SIP REFER: the carrier connects the caller to the destination and the caller leaves this call
        await lk.sip.transfer_sip_participant(api.TransferSIPParticipantRequest(
            room_name=call.room_name, participant_identity=sip.identity, transfer_to=destination, play_dialtone=False))
    except api.TwirpError as e:
        raise TransferError(f"The telephone network refused the transfer: {e.message}")
    finally:
        await lk.aclose()
    label = f"external:{entry.name} ({entry.number})"
    call_service.record_event(db, call, "transfer", actor_type="agent", actor_user_id=by_user.id,
                              payload={"type": "external", "to": label})
    call_service.close_legs(db, call, "transferred", kind="agent", user_id=by_user.id, transferred_to=label)
    call_service.open_leg(db, call, "external", party=label)
    log_action(db, call.company_id, by_user.id, "call.transferred", entity_type="voice_call", entity_id=call.id,
               changes={"to": label})
    db.commit()
    return {"transferred_to": label}


# ---------------------------------------------------------------- consultation (warm transfer)

def _token(room: str, user, role: str, publish: bool = True, hidden: bool = False, attrs: Optional[dict] = None) -> str:
    return (
        api.AccessToken(settings.LIVEKIT_API_KEY, settings.LIVEKIT_API_SECRET)
        .with_identity(call_service.agent_identity(user.id))
        .with_name(_user_name(user))
        .with_attributes({"agentconnect.role": role, "agentconnect.user_id": str(user.id), **(attrs or {})})
        .with_grants(api.VideoGrants(room_join=True, room=room, can_publish=publish, can_subscribe=True,
                                     can_publish_data=True, hidden=hidden))
        .to_jwt()
    )


def _consult(call: VoiceCall) -> dict:
    return (call.call_metadata or {}).get("consult") or {}


def _set_consult(db: Session, call: VoiceCall, consult: Optional[dict]) -> None:
    meta = dict(call.call_metadata or {})
    if consult:
        meta["consult"] = consult
    else:
        meta.pop("consult", None)
    call.call_metadata = meta
    db.commit()


async def start_consult(db: Session, call: VoiceCall, by_user, target_user_id: int) -> dict:
    if call.handled_by_user_id != by_user.id:
        raise TransferError("Only the agent on the call can consult")
    if _consult(call):
        raise TransferError("A consultation is already in progress")
    target = db.query(User).filter(User.id == target_user_id, User.company_id == call.company_id, User.is_active.is_(True)).first()
    if not target or target.id == by_user.id:
        raise TransferError("Choose another agent or supervisor")
    room = f"consult_{call.id}_{secrets.token_hex(4)}"
    call_service.set_hold(db, call, True, by_user.id)
    _set_consult(db, call, {"room": room, "from_user_id": by_user.id, "target_user_id": target.id})
    call_service.record_event(db, call, "consult_start", actor_type="agent", actor_user_id=by_user.id,
                              payload={"target_user_id": target.id})
    call_service.open_leg(db, call, "consult", user_id=target.id, party=_user_name(target))
    url = livekit_nodes.public_url()
    await call_service.broadcast(call.company_id, {
        "type": "phone_consult_offer", "ring_user_ids": [target.id], "call": call_service.serialize(call),
        "from_user": {"id": by_user.id, "name": _user_name(by_user)},
        "livekit_url": url, "token": _token(room, target, "consult"), "room": room,
    })
    await _keep_caller_company(call)
    return {"room": room, "livekit_url": url, "token": _token(room, by_user, "consult")}


async def complete_consult(db: Session, call: VoiceCall, by_user) -> dict:
    """Warm transfer: the consulted person takes over the call; the original agent leaves."""
    consult = _consult(call)
    if not consult or consult.get("from_user_id") != by_user.id:
        raise TransferError("No consultation in progress")
    target = db.query(User).filter(User.id == consult["target_user_id"]).one()
    call_service.record_event(db, call, "transfer", actor_type="agent", actor_user_id=by_user.id,
                              payload={"type": "consultative", "to": f"agent:{_user_name(target)}"})
    call_service.close_legs(db, call, "transferred", kind="agent", user_id=by_user.id,
                            transferred_to=f"agent:{_user_name(target)}")
    call_service.close_legs(db, call, "consult_done", kind="consult", user_id=target.id)
    call.handled_by_user_id = target.id
    session = db.query(ConversationSession).filter(ConversationSession.conversation_id == call.conversation_id).first()
    if session:
        session.assignee_id = target.id
    _set_consult(db, call, None)
    call_service.set_hold(db, call, False, by_user.id)
    log_action(db, call.company_id, by_user.id, "call.transferred", entity_type="voice_call", entity_id=call.id,
               changes={"to": f"agent:{_user_name(target)}", "type": "consultative"})
    db.commit()
    await recording_service.resume_if_paused(db, call, "transfer")
    await _agent_after_transfer(db, call, by_user.id)
    row = acd_service.set_state(db, target.id, call.company_id, "on_call", source="call", call_id=call.id)
    await acd_service.broadcast_state(call.company_id, row)
    url = livekit_nodes.public_url()
    await call_service.broadcast(call.company_id, {
        "type": "phone_call_handover", "user_id": target.id, "call": call_service.serialize(call),
        "livekit_url": url, "token": call_service.agent_token(call.room_name, target), "room": call.room_name,
        "consult_room": consult["room"],
    })
    await _close_room(consult["room"])
    return {"transferred_to": target.id}


async def cancel_consult(db: Session, call: VoiceCall, by_user) -> dict:
    consult = _consult(call)
    if not consult or consult.get("from_user_id") != by_user.id:
        raise TransferError("No consultation in progress")
    call_service.close_legs(db, call, "consult_cancelled", kind="consult", user_id=consult["target_user_id"])
    call_service.record_event(db, call, "consult_cancel", actor_type="agent", actor_user_id=by_user.id)
    _set_consult(db, call, None)
    call_service.set_hold(db, call, False, by_user.id)
    await _close_room(consult["room"])
    await call_service.broadcast(call.company_id, {"type": "phone_consult_ended", "call": call_service.serialize(call),
                                                   "room": consult["room"]})
    return {"ok": True}


async def _close_room(room: str) -> None:
    lk = _lk()
    try:
        await lk.room.delete_room(api.DeleteRoomRequest(room=room))
    except api.TwirpError:
        pass
    finally:
        await lk.aclose()


# ---------------------------------------------------------------- supervision

async def supervise(db: Session, call: VoiceCall, supervisor, mode: str) -> dict:
    """listen: hidden, can't speak. whisper: only the agent hears (the browser restricts who may subscribe). barge: joins the call."""
    if mode not in ("listen", "whisper", "barge"):
        raise TransferError("Unknown mode")
    if call.status not in call_service.ACTIVE_STATUSES:
        raise TransferError("The call has ended")
    token = _token(call.room_name, supervisor, "supervisor", publish=mode != "listen", hidden=mode == "listen",
                   attrs={"agentconnect.mode": mode})
    call_service.record_event(db, call, "supervise", actor_type="supervisor", actor_user_id=supervisor.id,
                              payload={"mode": mode})
    log_action(db, call.company_id, supervisor.id, f"call.supervise.{mode}", entity_type="voice_call", entity_id=call.id)
    db.commit()
    return {"livekit_url": livekit_nodes.public_url(), "token": token, "room": call.room_name,
            "mode": mode, "agent_identity": call_service.agent_identity(call.handled_by_user_id) if call.handled_by_user_id else None}
