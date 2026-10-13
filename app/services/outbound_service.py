"""
Outbound calls from the agent desktop (FR-CC-042..045) and callbacks (FR-CC-038).

Numbers are normalised to E.164 (default country +966), restricted to allowed country codes and
checked against the blocklist and the contact's do-not-contact flag (FR-CC-044). The agent joins
the call room right away (and hears ringback); LiveKit SIP dials out through the company's
outbound trunk. The network's answer becomes the call's outbound_result (FR-CC-045).
"""
import asyncio
import logging
import re
import uuid
from datetime import datetime
from typing import Optional

from livekit import api
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.contact_center import BlockedNumber, CallbackAttempt, CallPurposeCode, ContactCenterSettings, MissedCallTask
from app.models.conversation_session import ConversationSession
from app.models.voice_call import CallStatus, VoiceCall
from app.services import acd_service, call_service, contact_service, livekit_nodes

logger = logging.getLogger(__name__)

# SIP status code -> outbound result
SIP_RESULTS = {
    "486": "busy", "600": "busy", "603": "refused",
    "480": "no_answer", "408": "no_answer", "487": "no_answer",
    "404": "invalid_number", "484": "invalid_number", "604": "invalid_number", "410": "invalid_number",
}


class OutboundError(ValueError):
    pass


def get_settings(db: Session, company_id: int) -> ContactCenterSettings:
    row = db.query(ContactCenterSettings).filter(ContactCenterSettings.company_id == company_id).first()
    if not row:
        row = ContactCenterSettings(company_id=company_id, allowed_country_codes=["+966"])
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def normalize_number(raw: str, cc: ContactCenterSettings) -> str:
    """'05x xxx xxxx', '5xxxxxxxx', '009665…', '+9665…' -> '+9665…'; raises OutboundError if invalid / not allowed."""
    digits = re.sub(r"[\s\-().]", "", raw or "")
    if digits.startswith("00"):
        digits = "+" + digits[2:]
    elif digits.startswith("0"):
        digits = cc.default_country_code + digits[1:]
    elif not digits.startswith("+"):
        digits = cc.default_country_code + digits
    if not re.fullmatch(r"\+\d{8,15}", digits):
        raise OutboundError(f"'{raw}' is not a valid phone number")
    allowed = cc.allowed_country_codes or []
    if allowed and not any(digits.startswith(code) for code in allowed):
        raise OutboundError(f"Calls to {digits} are not allowed (allowed: {', '.join(allowed)})")
    return digits


def check_can_call(db: Session, company_id: int, number: str, contact=None) -> None:
    blocked = (db.query(BlockedNumber).filter(BlockedNumber.company_id == company_id, BlockedNumber.number == number,
                                              BlockedNumber.scope.in_(("outbound", "both"))).first())
    if blocked:
        raise OutboundError(f"{number} is blocked" + (f": {blocked.reason}" if blocked.reason else ""))
    if contact is not None and getattr(contact, "do_not_contact", False):
        raise OutboundError("This contact asked not to be contacted")


async def ensure_trunk(db: Session, cc: ContactCenterSettings) -> str:
    """Create (once) the LiveKit outbound trunk from the company settings."""
    if cc.outbound_trunk_id:
        return cc.outbound_trunk_id
    if not cc.outbound_trunk_address:
        raise OutboundError("Outbound calling isn't set up (Contact Center settings → Outbound)")
    from app.services.livekit_sip_service import _api
    lk = _api()
    try:
        trunk = await lk.sip.create_outbound_trunk(api.CreateSIPOutboundTrunkRequest(trunk=api.SIPOutboundTrunkInfo(
            name=f"agentconnect-outbound-{cc.company_id}", address=cc.outbound_trunk_address,
            numbers=[cc.outbound_caller_number] if cc.outbound_caller_number else [],
            auth_username=cc.outbound_auth_username or "", auth_password=cc.outbound_auth_password or "",
        )))
    finally:
        await lk.aclose()
    cc.outbound_trunk_id = trunk.sip_trunk_id
    db.commit()
    return trunk.sip_trunk_id


async def reset_trunk(db: Session, cc: ContactCenterSettings) -> None:
    """Settings changed: drop the LiveKit trunk so the next call recreates it."""
    if not cc.outbound_trunk_id:
        return
    from app.services.livekit_sip_service import _api
    lk = _api()
    try:
        await lk.sip.delete_trunk(api.DeleteSIPTrunkRequest(sip_trunk_id=cc.outbound_trunk_id))
    except api.TwirpError:
        pass
    finally:
        await lk.aclose()
    cc.outbound_trunk_id = None
    db.commit()


async def start_call(db: Session, user, raw_number: str, *, purpose_id: Optional[int] = None,
                     contact_id: Optional[int] = None, task: Optional[MissedCallTask] = None) -> dict:
    cc = get_settings(db, user.company_id)
    number = normalize_number(raw_number, cc)
    contact = None
    if contact_id:
        contact = contact_service.get_contact(db, contact_id, user.company_id)
    if contact is None:
        contact = contact_service.get_or_create_contact_for_channel(db, company_id=user.company_id, channel="voice",
                                                                   channel_identifier=number)
    check_can_call(db, user.company_id, number, contact)
    if purpose_id and not db.query(CallPurposeCode.id).filter(CallPurposeCode.id == purpose_id,
                                                              CallPurposeCode.company_id == user.company_id).first():
        raise OutboundError("Unknown call purpose")
    state = acd_service.get_state(db, user.id, user.company_id)
    if state.state == "on_call":
        raise OutboundError("Finish your current call first")
    trunk_id = await ensure_trunk(db, cc)

    sid = f"OUT_{uuid.uuid4().hex[:16]}"
    room = f"{settings.TELEPHONY_ROOM_PREFIX}_out_{uuid.uuid4().hex[:12]}"
    conv = ConversationSession(conversation_id=f"voice_{sid}", company_id=user.company_id, contact_id=contact.id,
                               channel="voice", status="assigned", assignee_id=user.id, is_ai_enabled=False)
    db.add(conv)
    call = VoiceCall(call_sid=sid, provider=call_service.PROVIDER, room_name=room, from_number=cc.outbound_caller_number or "",
                     to_number=number, company_id=user.company_id, conversation_id=conv.conversation_id, contact_id=contact.id,
                     status=CallStatus.RINGING.value, direction="outbound", started_at=datetime.utcnow(),
                     handled_by_user_id=user.id, call_purpose_id=purpose_id,
                     call_metadata={"callback_task_id": task.id} if task else {})
    db.add(call)
    db.commit()
    db.refresh(call)
    call_service.record_event(db, call, "dial", actor_type="agent", actor_user_id=user.id,
                              payload={"to": number, "purpose_id": purpose_id, "callback_task_id": task.id if task else None})
    attempt_id = None
    if task:
        attempt = CallbackAttempt(task_id=task.id, user_id=user.id, voice_call_id=call.id)
        db.add(attempt)
        task.attempts = (task.attempts or 0) + 1
        db.commit()
        attempt_id = attempt.id
    row = acd_service.set_state(db, user.id, user.company_id, "on_call", source="call", call_id=call.id)
    await acd_service.broadcast_state(user.company_id, row)
    asyncio.create_task(_dial(call.id, trunk_id, number, attempt_id))
    return {
        "call": call_service.serialize(call),
        "livekit_url": livekit_nodes.public_url(),
        "token": call_service.agent_token(room, user),
        "room": room,
    }


def _result_from_error(e: api.TwirpError) -> str:
    meta = getattr(e, "metadata", None) or {}
    code = str(meta.get("sip_status_code") or "")
    if not code:
        m = re.search(r"\b([4-6]\d\d)\b", e.message or "")
        code = m.group(1) if m else ""
    return SIP_RESULTS.get(code, "failed")


async def _dial(call_id: int, trunk_id: str, number: str, attempt_id: Optional[int]) -> None:
    """Dial out and wait for the answer; record the result."""
    from app.core.database import SessionLocal
    from app.services import recording_service
    from app.services.livekit_sip_service import _api

    lk = _api()
    result, error = "answered", None
    try:
        db0 = SessionLocal()
        try:
            room = db0.query(VoiceCall.room_name).filter(VoiceCall.id == call_id).scalar()
        finally:
            db0.close()
        await lk.sip.create_sip_participant(api.CreateSIPParticipantRequest(
            sip_trunk_id=trunk_id, sip_call_to=number, room_name=room, participant_identity=f"sip_{number}",
            participant_name=number, wait_until_answered=True, play_ringtone=True,
        ))
    except api.TwirpError as e:
        result, error = _result_from_error(e), e.message
    except Exception as e:  # network / config problem
        result, error = "failed", str(e)
    finally:
        await lk.aclose()

    db = SessionLocal()
    try:
        call = db.query(VoiceCall).filter(VoiceCall.id == call_id).one()
        call.outbound_result = result
        db.commit()
        if attempt_id and result != "answered":
            attempt = db.query(CallbackAttempt).filter(CallbackAttempt.id == attempt_id).one()
            attempt.result, attempt.ended_at = result, datetime.utcnow()
            db.commit()
        if result == "answered":
            call_service.mark_answered(db, call, None, actor_type="caller")
            call_service.record_event(db, call, "callee_answered", actor_type="caller")
            await call_service.broadcast(call.company_id, {"type": "phone_call_updated", "call": call_service.serialize(call)})
            recording_service.start_in_background(call.id)
        else:
            call_service.record_event(db, call, "dial_failed", payload={"result": result, "error": error})
            await call_service.end_call(db, call, ended_by="system")
    finally:
        db.close()


def finish_attempt(db: Session, call: VoiceCall) -> None:
    """When an answered callback ends, close its attempt row with the duration."""
    task_id = (call.call_metadata or {}).get("callback_task_id")
    if not task_id:
        return
    attempt = (db.query(CallbackAttempt).filter(CallbackAttempt.voice_call_id == call.id, CallbackAttempt.ended_at.is_(None))
               .first())
    if attempt:
        attempt.ended_at = datetime.utcnow()
        attempt.result = attempt.result or call.outbound_result or "answered"
        attempt.duration_seconds = call.talk_seconds
        db.commit()
