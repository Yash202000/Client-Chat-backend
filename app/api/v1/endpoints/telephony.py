"""
Telephony (LiveKit SIP contact centre) — phone numbers, LiveKit status and webhook.
"""
import json
import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from livekit import api
from sqlalchemy.orm import Session

from app.core.audit import log_action
from app.core.config import settings
from app.core.dependencies import get_db, require_permission
from app.models.agent import Agent
from app.models.call_event import CallEvent
from app.models.phone_number import PhoneNumber
from app.models.team import Team
from app.models.user import User
from app.models.voice_call import VoiceCall
from app.models.workflow import Workflow
from app.schemas.telephony import (
    PhoneNumberCreate, PhoneNumberUpdate, PhoneNumberResponse, PhoneNumberListResponse, TelephonyStatusResponse,
    CallAcceptResponse, CallEventResponse,
)
from app.services import (
    acd_service, call_service, livekit_nodes, livekit_sip_service, missed_call_service, outbound_service, recording_service,
    transfer_service,
)
from app.services.connection_manager import manager

logger = logging.getLogger(__name__)
router = APIRouter()


def _validate_targets(db: Session, company_id: int, workflow_id, agent_id, team_id=None, queue_id=None):
    if workflow_id is not None and not db.query(Workflow.id).filter(
            Workflow.id == workflow_id, Workflow.company_id == company_id).first():
        raise HTTPException(status_code=400, detail="Workflow not found")
    if agent_id is not None and not db.query(Agent.id).filter(
            Agent.id == agent_id, Agent.company_id == company_id).first():
        raise HTTPException(status_code=400, detail="Agent not found")
    if team_id is not None and not db.query(Team.id).filter(Team.id == team_id, Team.company_id == company_id).first():
        raise HTTPException(status_code=400, detail="Team not found")
    if queue_id is not None:
        from app.models.contact_center import CallQueue
        if not db.query(CallQueue.id).filter(CallQueue.id == queue_id, CallQueue.company_id == company_id).first():
            raise HTTPException(status_code=400, detail="Queue not found")


def _get_number(db: Session, company_id: int, phone_id: int) -> PhoneNumber:
    phone = db.query(PhoneNumber).filter(PhoneNumber.id == phone_id, PhoneNumber.company_id == company_id).first()
    if not phone:
        raise HTTPException(status_code=404, detail="Phone number not found")
    return phone


async def _sync(db: Session, phone: PhoneNumber) -> PhoneNumberResponse:
    """Push the number to LiveKit. A LiveKit failure is reported, not raised, so admins can fix config and re-sync."""
    error = None
    try:
        phone.provider_config = await livekit_sip_service.sync_phone_number(phone)
        db.commit()
        db.refresh(phone)
    except Exception as e:
        logger.exception(f"[telephony] LiveKit sync failed for number {phone.id}")
        error = str(e)
    resp = PhoneNumberResponse.model_validate(phone)
    resp.sync_error = error
    return resp


@router.get("/phone-numbers", response_model=PhoneNumberListResponse)
def list_phone_numbers(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("telephony:read")),
):
    numbers = db.query(PhoneNumber).filter(PhoneNumber.company_id == current_user.company_id).order_by(PhoneNumber.id).all()
    return PhoneNumberListResponse(phone_numbers=numbers, total=len(numbers))


@router.post("/phone-numbers", response_model=PhoneNumberResponse)
async def create_phone_number(
    data: PhoneNumberCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("telephony:manage")),
):
    number = data.number.strip()
    if db.query(PhoneNumber.id).filter(PhoneNumber.provider == data.provider, PhoneNumber.number == number).first():
        raise HTTPException(status_code=409, detail="This number is already configured")
    _validate_targets(db, current_user.company_id, data.entry_workflow_id, data.default_agent_id, data.ring_team_id, data.queue_id)

    phone = PhoneNumber(**data.model_dump(exclude={"number"}), number=number,
                        company_id=current_user.company_id, provider_config={})
    db.add(phone)
    db.commit()
    db.refresh(phone)
    log_action(db, current_user.company_id, current_user.id, "phone_number.created", entity_type="phone_number",
               entity_id=phone.id, entity_name=phone.number, changes=data.model_dump())
    db.commit()
    return await _sync(db, phone)


@router.put("/phone-numbers/{phone_id}", response_model=PhoneNumberResponse)
async def update_phone_number(
    phone_id: int,
    data: PhoneNumberUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("telephony:manage")),
):
    phone = _get_number(db, current_user.company_id, phone_id)
    changes = data.model_dump(exclude_unset=True)
    _validate_targets(db, current_user.company_id, changes.get("entry_workflow_id"),
                      changes.get("default_agent_id"), changes.get("ring_team_id"), changes.get("queue_id"))
    for key, value in changes.items():
        setattr(phone, key, value)
    log_action(db, current_user.company_id, current_user.id, "phone_number.updated", entity_type="phone_number",
               entity_id=phone.id, entity_name=phone.number, changes=changes)
    db.commit()
    db.refresh(phone)
    return await _sync(db, phone)


@router.post("/phone-numbers/{phone_id}/sync", response_model=PhoneNumberResponse)
async def resync_phone_number(
    phone_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("telephony:manage")),
):
    return await _sync(db, _get_number(db, current_user.company_id, phone_id))


@router.delete("/phone-numbers/{phone_id}")
async def delete_phone_number(
    phone_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("telephony:manage")),
):
    phone = _get_number(db, current_user.company_id, phone_id)
    try:
        await livekit_sip_service.delete_phone_number_resources(phone)
    except Exception as e:
        logger.warning(f"[telephony] LiveKit cleanup failed for number {phone.id}: {e}")
    log_action(db, current_user.company_id, current_user.id, "phone_number.deleted", entity_type="phone_number",
               entity_id=phone.id, entity_name=phone.number)
    db.delete(phone)
    db.commit()
    return {"ok": True}


@router.get("/status", response_model=TelephonyStatusResponse)
async def telephony_status(current_user: User = Depends(require_permission("telephony:read"))):
    result = TelephonyStatusResponse(
        livekit_url=settings.LIVEKIT_URL,
        livekit_reachable=False,
        voice_agent_name=settings.TELEPHONY_VOICE_AGENT_NAME,
        fanout_enabled=manager.fanout_enabled,
    )
    try:
        counts = await livekit_sip_service.status()
        result.livekit_reachable = True
        result.inbound_trunks = counts["inbound_trunks"]
        result.dispatch_rules = counts["dispatch_rules"]
    except Exception as e:
        result.error = str(e)
    return result


# ------------------------------------------------------------------ calls

def _get_call(db: Session, company_id: int, call_id: int) -> VoiceCall:
    call = db.query(VoiceCall).filter(VoiceCall.id == call_id, VoiceCall.company_id == company_id,
                                      VoiceCall.provider == call_service.PROVIDER).first()
    if not call:
        raise HTTPException(status_code=404, detail="Call not found")
    return call


@router.get("/calls")
def list_calls(
    scope: str = "active",
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("conversation:read")),
):
    """active: ringing / in-progress calls. recent: latest calls of any status."""
    if scope == "active":
        calls = call_service.active_calls(db, current_user.company_id)
    else:
        calls = (db.query(VoiceCall)
                 .filter(VoiceCall.company_id == current_user.company_id, VoiceCall.provider == call_service.PROVIDER)
                 .order_by(VoiceCall.started_at.desc()).limit(min(limit, 200)).all())
    return {"calls": [call_service.serialize(c) for c in calls]}


@router.get("/calls/{call_id}")
def get_call(
    call_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("conversation:read")),
):
    call = _get_call(db, current_user.company_id, call_id)
    events = db.query(CallEvent).filter(CallEvent.call_id == call.id).order_by(CallEvent.seq).all()
    return {"call": call_service.serialize(call), "events": [CallEventResponse.model_validate(e) for e in events],
            "legs": call_service.legs(db, call)}


@router.post("/calls/{call_id}/accept", response_model=CallAcceptResponse)
async def accept_call(
    call_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("conversation:update")),
):
    room = _get_call(db, current_user.company_id, call_id).room_name
    token = call_service.agent_token(room, current_user)  # before claiming, so a failure can't strand the call
    call = call_service.claim_call(db, call_id, current_user.company_id, current_user.id)
    if not call:
        raise HTTPException(status_code=409, detail="This call was already answered or has ended")
    await acd_service.on_accepted(db, call, current_user.id)
    await call_service.broadcast(call.company_id, {
        "type": "phone_call_taken", "call": call_service.serialize(call), "user_id": current_user.id,
    })
    return CallAcceptResponse(
        call=call_service.serialize(call),
        livekit_url=livekit_nodes.public_url(),
        token=token,
        room=call.room_name,
    )


@router.post("/calls/{call_id}/decline")
async def decline_call(
    call_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("conversation:update")),
):
    call = _get_call(db, current_user.company_id, call_id)
    call_service.record_event(db, call, "decline", actor_type="agent", actor_user_id=current_user.id)
    acd_service.on_declined(db, call, current_user.id)
    await acd_service.dispatch(db, current_user.company_id)
    return {"ok": True}


@router.post("/calls/{call_id}/hangup")
async def hang_up_call(
    call_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("conversation:update")),
):
    call = _get_call(db, current_user.company_id, call_id)
    if call.handled_by_user_id not in (None, current_user.id) and not current_user.is_super_admin:
        raise HTTPException(status_code=403, detail="Only the agent on this call can hang it up")
    await call_service.end_call(db, call, ended_by="agent", actor_user_id=current_user.id)
    return {"ok": True, "call": call_service.serialize(call)}


class WrapUpIn(BaseModel):
    disposition_code_id: Optional[int] = None
    note: Optional[str] = Field(None, max_length=4000)


class ManualCallIn(BaseModel):
    caller: str = Field(..., min_length=2, max_length=32)
    occurred_at: Optional[datetime] = None
    note: Optional[str] = Field(None, max_length=4000)
    phone_number_id: Optional[int] = None


def _require_handler(call: VoiceCall, user: User):
    if call.handled_by_user_id != user.id and not user.is_super_admin:
        raise HTTPException(status_code=403, detail="Only the agent on this call can do that")


@router.post("/calls/{call_id}/hold")
async def hold_call(call_id: int, db: Session = Depends(get_db),
                    current_user: User = Depends(require_permission("conversation:update"))):
    call = _get_call(db, current_user.company_id, call_id)
    _require_handler(call, current_user)
    call = call_service.set_hold(db, call, True, current_user.id)
    await call_service.broadcast(call.company_id, {"type": "phone_call_updated", "call": call_service.serialize(call)})
    return {"call": call_service.serialize(call)}


@router.post("/calls/{call_id}/resume")
async def resume_call(call_id: int, db: Session = Depends(get_db),
                      current_user: User = Depends(require_permission("conversation:update"))):
    call = _get_call(db, current_user.company_id, call_id)
    _require_handler(call, current_user)
    call = call_service.set_hold(db, call, False, current_user.id)
    await call_service.broadcast(call.company_id, {"type": "phone_call_updated", "call": call_service.serialize(call)})
    return {"call": call_service.serialize(call)}


@router.post("/calls/{call_id}/wrap-up")
async def wrap_up_call(call_id: int, data: WrapUpIn, db: Session = Depends(get_db),
                       current_user: User = Depends(require_permission("conversation:update"))):
    """After-call work: save the result code + note; the agent becomes ready."""
    call = _get_call(db, current_user.company_id, call_id)
    _require_handler(call, current_user)
    try:
        row = await acd_service.complete_wrap_up(db, call, current_user.id, data.disposition_code_id, data.note)
    except acd_service.StateError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await acd_service.dispatch(db, current_user.company_id)
    return {"call": call_service.serialize(call), "agent": acd_service.serialize_state(row)}


@router.post("/calls/manual")
def create_manual_call(data: ManualCallIn, db: Session = Depends(get_db),
                       current_user: User = Depends(require_permission("conversation:update"))):
    """CTI down (FR-CC-004): record a call by hand; flagged so it can be reconciled with the real call later."""
    import uuid
    from app.models.conversation_session import ConversationSession
    from app.services import contact_service

    phone = None
    if data.phone_number_id:
        phone = db.query(PhoneNumber).filter(PhoneNumber.id == data.phone_number_id,
                                             PhoneNumber.company_id == current_user.company_id).first()
    contact = contact_service.get_or_create_contact_for_channel(
        db, company_id=current_user.company_id, channel="voice", channel_identifier=data.caller)
    sid = f"MANUAL_{uuid.uuid4().hex[:12]}"
    session = ConversationSession(conversation_id=f"voice_{sid}", company_id=current_user.company_id,
                                  contact_id=contact.id, channel="voice", status="assigned",
                                  assignee_id=current_user.id, is_ai_enabled=False)
    db.add(session)
    when = (data.occurred_at or datetime.utcnow()).replace(tzinfo=None)
    call = VoiceCall(call_sid=sid, provider="manual", from_number=data.caller, to_number=phone.number if phone else "",
                     company_id=current_user.company_id, phone_number_id=phone.id if phone else None,
                     conversation_id=session.conversation_id, contact_id=contact.id, status="completed",
                     direction="inbound", started_at=when, answered_at=when, ended_at=when,
                     handled_by_user_id=current_user.id, manual_entry=True, disposition_note=data.note)
    db.add(call)
    db.commit()
    call_service.record_event(db, call, "manual_entry", actor_type="agent", actor_user_id=current_user.id,
                              payload={"note": data.note})
    log_action(db, current_user.company_id, current_user.id, "call.manual_entry", entity_type="voice_call",
               entity_id=call.id, changes={"caller": data.caller})
    db.commit()
    return {"call": call_service.serialize(call)}


@router.post("/calls/reconcile")
def reconcile_manual_calls(window_minutes: int = 15, db: Session = Depends(get_db),
                           current_user: User = Depends(require_permission("telephony:manage"))):
    """Match unreconciled manual records to real calls from the same number within the time window."""
    manual = db.query(VoiceCall).filter(VoiceCall.company_id == current_user.company_id, VoiceCall.manual_entry.is_(True),
                                        VoiceCall.reconciled_with_call_id.is_(None)).all()
    matched = []
    for m in manual:
        window = timedelta(minutes=window_minutes)
        real = (db.query(VoiceCall).filter(VoiceCall.company_id == m.company_id, VoiceCall.manual_entry.is_(False),
                                           VoiceCall.from_number == m.from_number,
                                           VoiceCall.started_at.between(m.started_at - window, m.started_at + window))
                .order_by(VoiceCall.started_at).first())
        if real:
            m.reconciled_with_call_id = real.id
            call_service.record_event(db, m, "reconciled", actor_type="system", payload={"call_id": real.id})
            matched.append({"manual_call_id": m.id, "call_id": real.id})
    db.commit()
    return {"matched": matched, "unmatched": len(manual) - len(matched)}


class TransferIn(BaseModel):
    target_type: str = Field(..., pattern="^(agent|queue|external)$")
    target_id: Optional[int] = None  # user id, queue id or directory entry id
    number: Optional[str] = None     # external number (must be in the directory and transfer-allowed)
    note: Optional[str] = Field(None, max_length=1000)


class ConsultIn(BaseModel):
    target_user_id: int


class SuperviseIn(BaseModel):
    mode: str = Field(..., pattern="^(listen|whisper|barge)$")


class QualityIn(BaseModel):
    jitter_ms: Optional[float] = None
    packet_loss_pct: Optional[float] = None
    round_trip_ms: Optional[float] = None
    mos: Optional[float] = None


def _transfer_errors(fn):
    async def run(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except transfer_service.TransferError as e:
            raise HTTPException(status_code=400, detail=str(e))
    return run


@router.post("/calls/{call_id}/transfer")
async def transfer_call(call_id: int, data: TransferIn, db: Session = Depends(get_db),
                        current_user: User = Depends(require_permission("conversation:update"))):
    call = _get_call(db, current_user.company_id, call_id)
    return await _transfer_errors(transfer_service.blind_transfer)(
        db, call, current_user, target_type=data.target_type, target_id=data.target_id, number=data.number,
        note=data.note or "")


@router.post("/calls/{call_id}/consult")
async def consult_start(call_id: int, data: ConsultIn, db: Session = Depends(get_db),
                        current_user: User = Depends(require_permission("conversation:update"))):
    call = _get_call(db, current_user.company_id, call_id)
    return await _transfer_errors(transfer_service.start_consult)(db, call, current_user, data.target_user_id)


@router.post("/calls/{call_id}/consult/complete")
async def consult_complete(call_id: int, db: Session = Depends(get_db),
                           current_user: User = Depends(require_permission("conversation:update"))):
    call = _get_call(db, current_user.company_id, call_id)
    return await _transfer_errors(transfer_service.complete_consult)(db, call, current_user)


@router.post("/calls/{call_id}/consult/cancel")
async def consult_cancel(call_id: int, db: Session = Depends(get_db),
                         current_user: User = Depends(require_permission("conversation:update"))):
    call = _get_call(db, current_user.company_id, call_id)
    return await _transfer_errors(transfer_service.cancel_consult)(db, call, current_user)


@router.post("/calls/{call_id}/supervise")
async def supervise_call(call_id: int, data: SuperviseIn, db: Session = Depends(get_db),
                         current_user: User = Depends(require_permission("calls:supervise"))):
    call = _get_call(db, current_user.company_id, call_id)
    return await _transfer_errors(transfer_service.supervise)(db, call, current_user, data.mode)


@router.get("/calls/{call_id}/recording")
def call_recording(call_id: int, download: bool = False, db: Session = Depends(get_db),
                   current_user: User = Depends(require_permission("conversation:read"))):
    """Separate permissions for listening and downloading (FR-CC-052 / BR-018); every access is logged."""
    needed = "recordings:download" if download else "recordings:listen"
    perms = {p.name for p in (current_user.role.permissions if current_user.role else [])}
    if not current_user.is_super_admin and needed not in perms:
        raise HTTPException(status_code=403, detail=f"Requires '{needed}'")
    call = _get_call(db, current_user.company_id, call_id)
    if call.recording_status != "completed" or not recording_service.part_keys(call):
        raise HTTPException(status_code=404, detail=f"No recording available ({call.recording_status or 'not recorded'})")
    urls = recording_service.access_urls(db, call, current_user.id, download)
    # a recording that was paused has several parts, played one after the other
    return {"url": urls[0], "parts": urls, "expires_in": 300}


class RecordingPauseIn(BaseModel):
    reason: Optional[str] = Field(None, max_length=255)


async def _pause_or_resume(db: Session, call_id: int, user: User, reason: Optional[str], resume: bool) -> dict:
    call = _get_call(db, user.company_id, call_id)
    perms = {p.name for p in (user.role.permissions if user.role else [])}
    if call.handled_by_user_id != user.id and not user.is_super_admin and "calls:supervise" not in perms:
        raise HTTPException(status_code=403, detail="Only the agent on the call or a supervisor can do this")
    try:
        fn = recording_service.resume if resume else recording_service.pause
        result = await fn(db, call, user.id, reason=reason or "")
    except recording_service.RecordingError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await call_service.broadcast(call.company_id, {"type": "phone_call_updated", "call": call_service.serialize(call)})
    return result


@router.post("/calls/{call_id}/recording/pause")
async def pause_recording(call_id: int, data: RecordingPauseIn, db: Session = Depends(get_db),
                          current_user: User = Depends(require_permission("recordings:pause"))):
    """FR-CC-051: stop recording (e.g. card details); the paused stretch is never recorded. Audited."""
    return await _pause_or_resume(db, call_id, current_user, data.reason, resume=False)


@router.post("/calls/{call_id}/recording/resume")
async def resume_recording(call_id: int, data: RecordingPauseIn, db: Session = Depends(get_db),
                           current_user: User = Depends(require_permission("recordings:pause"))):
    return await _pause_or_resume(db, call_id, current_user, data.reason, resume=True)


@router.post("/calls/{call_id}/quality")
def report_quality(call_id: int, data: QualityIn, db: Session = Depends(get_db),
                   current_user: User = Depends(require_permission("conversation:update"))):
    """Voice quality measured by the agent's browser at the end of the call (NFR-007)."""
    call = _get_call(db, current_user.company_id, call_id)
    quality = dict(call.quality or {})
    quality[str(current_user.id)] = {k: v for k, v in data.model_dump().items() if v is not None}
    call.quality = quality
    db.commit()
    return {"ok": True}


# ------------------------------------------------------------------ outbound calls + missed-call tasks

class OutboundIn(BaseModel):
    number: str = Field(..., min_length=2, max_length=32)
    purpose_id: Optional[int] = None
    contact_id: Optional[int] = None


class AssignIn(BaseModel):
    user_id: Optional[int] = None  # None = unassign


class CloseTaskIn(BaseModel):
    result: str
    comment: Optional[str] = Field(None, max_length=2000)


def _get_task(db: Session, company_id: int, task_id: int):
    from app.models.contact_center import MissedCallTask
    task = db.query(MissedCallTask).filter(MissedCallTask.id == task_id, MissedCallTask.company_id == company_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Missed call not found")
    return task


def _has(user: User, perm: str) -> bool:
    return user.is_super_admin or perm in {p.name for p in (user.role.permissions if user.role else [])}


@router.post("/calls/outbound")
async def outbound_call(data: OutboundIn, db: Session = Depends(get_db),
                        current_user: User = Depends(require_permission("conversation:update"))):
    try:
        return await outbound_service.start_call(db, current_user, data.number, purpose_id=data.purpose_id,
                                                 contact_id=data.contact_id)
    except outbound_service.OutboundError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/missed-calls")
def list_missed_calls(status: Optional[str] = None, mine: bool = False, limit: int = 100, db: Session = Depends(get_db),
                      current_user: User = Depends(require_permission("conversation:read"))):
    """Missed / abandoned calls to follow up (FR-CC-035). Agents without supervise rights see their own tasks only."""
    from app.models.contact_center import MissedCallTask
    q = db.query(MissedCallTask).filter(MissedCallTask.company_id == current_user.company_id)
    if mine or not _has(current_user, "calls:supervise"):
        q = q.filter(MissedCallTask.assigned_to_user_id == current_user.id)
    if status == "open":
        q = q.filter(MissedCallTask.status != "closed")
    elif status:
        q = q.filter(MissedCallTask.status == status)
    tasks = q.order_by(MissedCallTask.created_at.desc()).limit(min(limit, 500)).all()
    names = {u.id: (" ".join(x for x in [u.first_name, u.last_name] if x) or u.email)
             for u in db.query(User).filter(User.company_id == current_user.company_id).all()}
    return {"tasks": [missed_call_service.serialize(t, names) for t in tasks],
            "workload": missed_call_service.workload(db, current_user.company_id) if _has(current_user, "calls:supervise") else None}


@router.get("/missed-calls/{task_id}")
def get_missed_call(task_id: int, db: Session = Depends(get_db),
                    current_user: User = Depends(require_permission("conversation:read"))):
    task = _get_task(db, current_user.company_id, task_id)
    return {"task": missed_call_service.serialize(task), "attempts": missed_call_service.attempts(db, task)}


@router.post("/missed-calls/{task_id}/assign")
async def assign_missed_call(task_id: int, data: AssignIn, db: Session = Depends(get_db),
                             current_user: User = Depends(require_permission("calls:supervise"))):
    task = _get_task(db, current_user.company_id, task_id)
    try:
        task = missed_call_service.assign(db, task, data.user_id, current_user.id)
    except missed_call_service.TaskError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await call_service.broadcast(current_user.company_id, {"type": "missed_call_assigned", "task": missed_call_service.serialize(task)})
    return {"task": missed_call_service.serialize(task)}


@router.post("/missed-calls/{task_id}/callback")
async def callback_missed_call(task_id: int, db: Session = Depends(get_db),
                               current_user: User = Depends(require_permission("conversation:update"))):
    """Call the caller back from the list (FR-CC-038); the attempt is logged on the task."""
    from app.models.contact_center import CallPurposeCode
    task = _get_task(db, current_user.company_id, task_id)
    if task.status == "closed":
        raise HTTPException(status_code=400, detail="This task is closed")
    if task.assigned_to_user_id not in (None, current_user.id) and not _has(current_user, "calls:supervise"):
        raise HTTPException(status_code=403, detail="This missed call is assigned to someone else")
    if task.assigned_to_user_id is None:
        missed_call_service.assign(db, task, current_user.id, current_user.id)
    purpose = db.query(CallPurposeCode).filter(CallPurposeCode.company_id == current_user.company_id,
                                               CallPurposeCode.name.ilike("callback%")).first()
    try:
        return await outbound_service.start_call(db, current_user, task.caller_number, contact_id=task.contact_id,
                                                 purpose_id=purpose.id if purpose else None, task=task)
    except outbound_service.OutboundError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/missed-calls/{task_id}/close")
def close_missed_call(task_id: int, data: CloseTaskIn, db: Session = Depends(get_db),
                      current_user: User = Depends(require_permission("conversation:update"))):
    task = _get_task(db, current_user.company_id, task_id)
    if task.assigned_to_user_id not in (None, current_user.id) and not _has(current_user, "calls:supervise"):
        raise HTTPException(status_code=403, detail="This missed call is assigned to someone else")
    try:
        task = missed_call_service.close(db, task, current_user.id, data.result, data.comment)
    except missed_call_service.TaskError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"task": missed_call_service.serialize(task)}


# ------------------------------------------------------------------ LiveKit webhook

SIP = api.ParticipantInfo.Kind.SIP
AGENT = api.ParticipantInfo.Kind.AGENT


async def _on_participant_joined(db: Session, room: str, p) -> None:
    attrs = dict(p.attributes)
    if p.kind == SIP and room.startswith(settings.TELEPHONY_ROOM_PREFIX + "_out_"):
        # outbound call: the record already exists; the callee is being dialled (answer is set by the dialler)
        call = call_service.find_call_by_room(db, room)
        if call:
            call_service.record_event(db, call, "callee_ringing", actor_type="caller")
        return
    if p.kind == SIP:
        phone_id = attrs.get("agentconnect.phone_number_id")
        phone = db.query(PhoneNumber).filter(PhoneNumber.id == int(phone_id)).first() if phone_id else None
        if not phone:
            logger.warning(f"[telephony] SIP participant in {room} without a known phone number: {attrs}")
            return
        call, created = call_service.get_or_create_inbound_call(
            db, phone=phone, room_name=room, sip_call_id=attrs.get("sip.callID") or room,
            caller=attrs.get("sip.phoneNumber"), called=attrs.get("sip.trunkPhoneNumber"),
        )
        if created:
            await call_service.announce_new_call(db, call)
        if created and phone.routing_mode == "direct" and call.handled_by_user_id is None:
            await call_service.route_to_agents(db, call, phone)
        return

    call = call_service.find_call_by_room(db, room)
    if not call:
        return
    role = dict(p.attributes).get("agentconnect.role", "agent")
    if p.kind == AGENT:  # voice process picked up (AI / IVR, or keeping the caller company on hold)
        call_service.record_event(db, call, "ai_joined", actor_type="ai")
        call_service.open_leg(db, call, "ai", party="AI")
        call_service.mark_answered(db, call, None, actor_type="ai")
    elif (uid := call_service.user_id_from_identity(p.identity)) is not None:
        if role == "supervisor":
            call_service.record_event(db, call, "supervisor_joined", actor_type="supervisor", actor_user_id=uid,
                                      payload={"mode": dict(p.attributes).get("agentconnect.mode")})
            call_service.open_leg(db, call, "supervisor", user_id=uid, party=p.name)
        else:
            call_service.record_event(db, call, "agent_joined", actor_type="agent", actor_user_id=uid)
            call_service.open_leg(db, call, "agent", user_id=uid, party=p.name)
            if call.direction != "outbound":  # outbound calls are answered when the callee picks up
                call_service.mark_answered(db, call, uid)
    else:
        return
    db.refresh(call)
    if call.answered_at and not call.recording_status and role != "supervisor":
        recording_service.start_in_background(call.id)
    await call_service.broadcast(call.company_id, {"type": "phone_call_updated", "call": call_service.serialize(call)})


async def _on_participant_left(db: Session, room: str, p) -> None:
    call = call_service.find_call_by_room(db, room)
    if not call:
        return
    if p.kind == SIP:
        await call_service.end_call(db, call, ended_by="callee" if call.direction == "outbound" else "caller")
    elif p.kind == AGENT:
        call_service.close_legs(db, call, "left", kind="ai")
    elif (uid := call_service.user_id_from_identity(p.identity)) is not None:
        if dict(p.attributes).get("agentconnect.role") == "supervisor":
            call_service.record_event(db, call, "supervisor_left", actor_type="supervisor", actor_user_id=uid)
            call_service.close_legs(db, call, "left", kind="supervisor", user_id=uid)
            return
        call_service.record_event(db, call, "agent_left", actor_type="agent", actor_user_id=uid)
        call_service.close_legs(db, call, "left", kind="agent", user_id=uid)
        db.refresh(call)
        # The handling agent leaving ends the call; after a transfer handled_by has already moved on
        if uid == call.handled_by_user_id and call.status in call_service.ACTIVE_STATUSES:
            await call_service.end_call(db, call, ended_by="agent", actor_user_id=uid)


@router.post("/livekit/webhook")
async def livekit_webhook(request: Request, db: Session = Depends(get_db)):
    """
    LiveKit server webhook (configured in telephony/livekit.yaml), signed with the LiveKit API key.
    Creates call records, rings agents for direct numbers, and records answer / hang-up events.
    """
    body = (await request.body()).decode()
    receiver = api.WebhookReceiver(api.TokenVerifier(settings.LIVEKIT_API_KEY, settings.LIVEKIT_API_SECRET))
    try:
        event = receiver.receive(body, request.headers.get("Authorization", ""))
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    if event.event == "egress_ended" and event.HasField("egress_info"):
        recording_service.on_egress_finished(db, event.egress_info)
        return {"ok": True}

    room = event.room.name if event.HasField("room") else ""
    if not room.startswith(settings.TELEPHONY_ROOM_PREFIX + "_"):
        return {"ok": True}  # not a phone call room (e.g. internal video calls)

    p = event.participant if event.HasField("participant") else None
    logger.info(f"[telephony] webhook {event.event} room={room} participant={p.identity if p else None}")
    try:
        if event.event == "participant_joined" and p is not None:
            await _on_participant_joined(db, room, p)
        elif event.event == "participant_left" and p is not None:
            await _on_participant_left(db, room, p)
        elif event.event == "room_finished":
            call = call_service.find_call_by_room(db, room)
            if call:
                await call_service.end_call(db, call, ended_by="system", hang_up=False)
    except Exception:
        logger.exception(f"[telephony] webhook {event.event} failed for room {room}")
        raise
    return {"ok": True}
