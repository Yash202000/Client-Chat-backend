"""
Contact-centre configuration and agent state (M3): queues + members, reason codes, disposition
codes, shifts, extensions, number directory; the agent's own status; live agent list.
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import log_action
from app.core.dependencies import get_db, require_permission
from app.models.contact_center import (
    AgentReasonCode, AgentState, BlockedNumber, CallPurposeCode, CallQueue, CallQueueMember, DirectoryEntry,
    DispositionCode, Extension, NOT_READY_STATES, QaEvaluation, QaForm, Shift, ShiftAssignment, SipAccount,
)
from app.models.user import User
from app.services import acd_service, cc_report_service, outbound_service, qa_retention_service

router = APIRouter()
READ = require_permission("telephony:read")
MANAGE = require_permission("telephony:manage")
AGENT = require_permission("conversation:update")  # anyone who handles conversations can take calls


# ------------------------------------------------------------------ schemas

class QueueIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    description: Optional[str] = None
    priority: int = 0
    required_skill: Optional[str] = None
    is_open: bool = True
    is_supervisor_queue: bool = False
    offer_timeout_seconds: int = Field(20, ge=5, le=120)
    max_wait_seconds: int = Field(120, ge=10, le=3600)
    overflow_text: Optional[str] = None
    wrap_up_seconds: int = Field(30, ge=0, le=900)
    announce_wait_time: bool = False
    announce_interval_seconds: int = Field(60, ge=30, le=600)
    member_user_ids: List[int] = []


class ReasonCodeIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    state: str = Field("break", pattern="^(break|training|meeting|unavailable)$")
    allowed_role_ids: Optional[List[int]] = None
    is_active: bool = True


class DispositionIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    requires_note: bool = False
    is_active: bool = True


class Slot(BaseModel):
    days: List[int]
    start: str = Field(..., pattern=r"^\d{2}:\d{2}$")
    end: str = Field(..., pattern=r"^\d{2}:\d{2}$")


class ShiftIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    timezone: str = "Asia/Riyadh"
    schedule: List[Slot] = []
    is_active: bool = True
    agent_user_ids: List[int] = []
    supervisor_user_ids: List[int] = []


class ExtensionIn(BaseModel):
    user_id: int
    extension: str = Field(..., pattern=r"^\d{2,8}$")


class DirectoryIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    number: str = Field(..., min_length=2, max_length=32)
    kind: str = Field("external", pattern="^(entity|external)$")
    transfer_allowed: bool = False
    notes: Optional[str] = None


class StateIn(BaseModel):
    state: str
    reason_code_id: Optional[int] = None


# ------------------------------------------------------------------ helpers

def _company_users(db: Session, company_id: int, user_ids: List[int]) -> List[int]:
    found = {uid for (uid,) in db.query(User.id).filter(User.company_id == company_id, User.id.in_(user_ids)).all()}
    missing = set(user_ids) - found
    if missing:
        raise HTTPException(status_code=400, detail=f"Unknown users: {sorted(missing)}")
    return list(found)


def _get(db: Session, model, company_id: int, obj_id: int):
    obj = db.query(model).filter(model.id == obj_id, model.company_id == company_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Not found")
    return obj


def _commit(db: Session, what: str):
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail=f"{what} already exists")


def _queue_out(q: CallQueue) -> dict:
    return {c.name: getattr(q, c.name) for c in CallQueue.__table__.columns} | {
        "member_user_ids": [m.user_id for m in q.members]}


def _shift_out(db: Session, s: Shift) -> dict:
    assignments = db.query(ShiftAssignment).filter(ShiftAssignment.shift_id == s.id).all()
    return {"id": s.id, "name": s.name, "timezone": s.timezone, "schedule": s.schedule, "is_active": s.is_active,
            "agent_user_ids": [a.user_id for a in assignments if a.role == "agent"],
            "supervisor_user_ids": [a.user_id for a in assignments if a.role == "supervisor"]}


def _row(obj) -> dict:
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}


# ------------------------------------------------------------------ agent status

@router.get("/me/state")
def my_state(db: Session = Depends(get_db), current_user: User = Depends(AGENT)):
    row = acd_service.get_state(db, current_user.id, current_user.company_id)
    codes = db.query(AgentReasonCode).filter(AgentReasonCode.company_id == current_user.company_id,
                                             AgentReasonCode.is_active.is_(True)).order_by(AgentReasonCode.name).all()
    usable = [c for c in codes if not c.allowed_role_ids or current_user.role_id in c.allowed_role_ids]
    return {"agent": acd_service.serialize_state(row), "reason_codes": [_row(c) for c in usable]}


@router.put("/me/state")
async def set_my_state(data: StateIn, db: Session = Depends(get_db), current_user: User = Depends(AGENT)):
    try:
        row = acd_service.set_state(db, current_user.id, current_user.company_id, data.state,
                                    reason_code_id=data.reason_code_id, changed_by=current_user.id,
                                    role_id=current_user.role_id)
    except acd_service.StateError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await acd_service.broadcast_state(current_user.company_id, row)
    if row.state == "ready":
        await acd_service.dispatch(db, current_user.company_id)  # a waiting call may go to this agent now
    return {"agent": acd_service.serialize_state(row)}


@router.get("/agents")
def live_agents(db: Session = Depends(get_db), current_user: User = Depends(require_permission("conversation:read"))):
    """Every agent's current state (wallboard / supervisor view)."""
    rows = (db.query(User, AgentState).outerjoin(AgentState, AgentState.user_id == User.id)
            .filter(User.company_id == current_user.company_id, User.is_active.is_(True)).all())
    out = []
    for user, state in rows:
        out.append({
            "user_id": user.id,
            "name": " ".join(p for p in [user.first_name, user.last_name] if p) or user.email,
            "presence": user.presence_status,
            **(acd_service.serialize_state(state) if state else {"state": "logged_out", "since": None, "reason": None}),
        })
    return {"agents": out}


# ------------------------------------------------------------------ queues

@router.get("/queues")
def list_queues(db: Session = Depends(get_db), current_user: User = Depends(READ)):
    queues = db.query(CallQueue).filter(CallQueue.company_id == current_user.company_id).order_by(CallQueue.name).all()
    return {"queues": [_queue_out(q) for q in queues]}


@router.post("/queues")
def create_queue(data: QueueIn, db: Session = Depends(get_db), current_user: User = Depends(MANAGE)):
    members = _company_users(db, current_user.company_id, data.member_user_ids)
    q = CallQueue(company_id=current_user.company_id, **data.model_dump(exclude={"member_user_ids"}))
    q.members = [CallQueueMember(user_id=uid) for uid in members]
    db.add(q)
    log_action(db, current_user.company_id, current_user.id, "call_queue.created", entity_type="call_queue", entity_name=q.name)
    _commit(db, "A queue with this name")
    db.refresh(q)
    return _queue_out(q)


@router.put("/queues/{queue_id}")
def update_queue(queue_id: int, data: QueueIn, db: Session = Depends(get_db), current_user: User = Depends(MANAGE)):
    q = _get(db, CallQueue, current_user.company_id, queue_id)
    members = _company_users(db, current_user.company_id, data.member_user_ids)
    for key, value in data.model_dump(exclude={"member_user_ids"}).items():
        setattr(q, key, value)
    existing = {m.user_id: m for m in q.members}
    q.members = [existing.get(uid) or CallQueueMember(user_id=uid) for uid in members]
    log_action(db, current_user.company_id, current_user.id, "call_queue.updated", entity_type="call_queue",
               entity_id=q.id, entity_name=q.name, changes=data.model_dump())
    _commit(db, "A queue with this name")
    db.refresh(q)
    return _queue_out(q)


@router.delete("/queues/{queue_id}")
def delete_queue(queue_id: int, db: Session = Depends(get_db), current_user: User = Depends(MANAGE)):
    q = _get(db, CallQueue, current_user.company_id, queue_id)
    log_action(db, current_user.company_id, current_user.id, "call_queue.deleted", entity_type="call_queue", entity_id=q.id, entity_name=q.name)
    db.delete(q)
    db.commit()
    return {"ok": True}


# ------------------------------------------------------------------ simple lists (reason codes, dispositions, directory)

def _simple_crud(path: str, model, schema, label: str, audit: str):
    @router.get(f"/{path}", name=f"list_{path}")
    def list_items(db: Session = Depends(get_db), current_user: User = Depends(READ)):
        items = db.query(model).filter(model.company_id == current_user.company_id).order_by(model.name).all()
        return {"items": [_row(i) for i in items]}

    @router.post(f"/{path}", name=f"create_{path}")
    def create_item(data: schema, db: Session = Depends(get_db), current_user: User = Depends(MANAGE)):
        item = model(company_id=current_user.company_id, **data.model_dump())
        db.add(item)
        log_action(db, current_user.company_id, current_user.id, f"{audit}.created", entity_type=audit, entity_name=data.name)
        _commit(db, label)
        db.refresh(item)
        return _row(item)

    @router.put(f"/{path}/{{item_id}}", name=f"update_{path}")
    def update_item(item_id: int, data: schema, db: Session = Depends(get_db), current_user: User = Depends(MANAGE)):
        item = _get(db, model, current_user.company_id, item_id)
        for key, value in data.model_dump().items():
            setattr(item, key, value)
        log_action(db, current_user.company_id, current_user.id, f"{audit}.updated", entity_type=audit,
                   entity_id=item.id, entity_name=data.name, changes=data.model_dump())
        _commit(db, label)
        return _row(item)

    @router.delete(f"/{path}/{{item_id}}", name=f"delete_{path}")
    def delete_item(item_id: int, db: Session = Depends(get_db), current_user: User = Depends(MANAGE)):
        item = _get(db, model, current_user.company_id, item_id)
        log_action(db, current_user.company_id, current_user.id, f"{audit}.deleted", entity_type=audit,
                   entity_id=item.id, entity_name=item.name)
        db.delete(item)
        db.commit()
        return {"ok": True}


class PurposeIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    is_active: bool = True


class BlockedIn(BaseModel):
    number: str = Field(..., min_length=2, max_length=32)
    scope: str = Field("outbound", pattern="^(outbound|inbound|both)$")
    reason: Optional[str] = Field(None, max_length=255)


class SettingsIn(BaseModel):
    abandon_threshold_seconds: int = Field(5, ge=0, le=300)
    create_callback_tasks: bool = True
    default_country_code: str = Field("+966", pattern=r"^\+\d{1,4}$")
    allowed_country_codes: List[str] = ["+966"]
    outbound_caller_number: Optional[str] = None
    outbound_trunk_address: Optional[str] = None
    outbound_auth_username: Optional[str] = None
    outbound_auth_password: Optional[str] = None  # write-only; empty keeps the saved password
    refusal_comment_required: bool = True
    recording_retention_days: Optional[int] = None  # None = keep for life
    call_history_retention_days: Optional[int] = None
    chat_retention_days: Optional[int] = None
    service_level_seconds: int = Field(20, ge=1, le=600)


_simple_crud("reason-codes", AgentReasonCode, ReasonCodeIn, "This reason code", "reason_code")
_simple_crud("call-purposes", CallPurposeCode, PurposeIn, "This purpose", "call_purpose")


@router.get("/call-purposes/active")
def active_purposes(db: Session = Depends(get_db), current_user: User = Depends(AGENT)):
    items = db.query(CallPurposeCode).filter(CallPurposeCode.company_id == current_user.company_id,
                                             CallPurposeCode.is_active.is_(True)).order_by(CallPurposeCode.name).all()
    return {"items": [_row(i) for i in items]}


def _settings_out(cc) -> dict:
    out = _row(cc)
    out.pop("outbound_auth_password", None)
    out["outbound_password_set"] = bool(cc.outbound_auth_password)
    out["outbound_ready"] = bool(cc.outbound_trunk_address)
    return out


@router.get("/settings")
def get_cc_settings(db: Session = Depends(get_db), current_user: User = Depends(READ)):
    return _settings_out(outbound_service.get_settings(db, current_user.company_id))


@router.put("/settings")
async def update_cc_settings(data: SettingsIn, db: Session = Depends(get_db), current_user: User = Depends(MANAGE)):
    cc = outbound_service.get_settings(db, current_user.company_id)
    changes = data.model_dump(exclude={"outbound_auth_password"})
    try:
        for key, label in (("recording_retention_days", "Recordings"), ("call_history_retention_days", "Call history"),
                           ("chat_retention_days", "Chat conversations")):
            qa_retention_service.validate_days(changes[key], label)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    # shortening a period starts the grace period before anything is removed
    for key in ("recording_retention_days", "call_history_retention_days", "chat_retention_days"):
        old, new = getattr(cc, key), changes[key]
        if new is not None and (old is None or new < old):
            from datetime import datetime, timezone
            cc.retention_changed_at = datetime.now(timezone.utc)
    trunk_changed = any(getattr(cc, k) != v for k, v in changes.items() if k.startswith("outbound_")) or bool(data.outbound_auth_password)
    for k, v in changes.items():
        setattr(cc, k, v)
    if data.outbound_auth_password:
        cc.outbound_auth_password = data.outbound_auth_password
    log_action(db, current_user.company_id, current_user.id, "contact_center.settings_updated", entity_type="contact_center",
               changes=changes)
    db.commit()
    if trunk_changed:
        await outbound_service.reset_trunk(db, cc)  # recreated on the next outbound call
    return _settings_out(cc)


@router.get("/blocklist")
def list_blocked(db: Session = Depends(get_db), current_user: User = Depends(READ)):
    rows = db.query(BlockedNumber).filter(BlockedNumber.company_id == current_user.company_id).order_by(BlockedNumber.number).all()
    return {"items": [_row(r) for r in rows]}


@router.post("/blocklist")
def add_blocked(data: BlockedIn, db: Session = Depends(get_db), current_user: User = Depends(MANAGE)):
    cc = outbound_service.get_settings(db, current_user.company_id)
    try:
        number = outbound_service.normalize_number(data.number, cc) if not data.number.startswith("sip:") else data.number
    except outbound_service.OutboundError:
        number = data.number.strip()  # keep short codes / special numbers as typed
    row = BlockedNumber(company_id=current_user.company_id, number=number, scope=data.scope, reason=data.reason,
                        created_by_user_id=current_user.id)
    db.add(row)
    log_action(db, current_user.company_id, current_user.id, "blocklist.added", entity_type="blocked_number",
               entity_name=number, changes=data.model_dump())
    _commit(db, "This number")
    return _row(row)


@router.delete("/blocklist/{item_id}")
def remove_blocked(item_id: int, db: Session = Depends(get_db), current_user: User = Depends(MANAGE)):
    row = _get(db, BlockedNumber, current_user.company_id, item_id)
    log_action(db, current_user.company_id, current_user.id, "blocklist.removed", entity_type="blocked_number",
               entity_name=row.number)
    db.delete(row)
    db.commit()
    return {"ok": True}
_simple_crud("dispositions", DispositionCode, DispositionIn, "This disposition", "disposition_code")
_simple_crud("directory", DirectoryEntry, DirectoryIn, "This entry", "directory_entry")


@router.get("/dispositions/active")
def active_dispositions(db: Session = Depends(get_db), current_user: User = Depends(AGENT)):
    """For the agent's wrap-up form (agents may not have telephony:read)."""
    items = db.query(DispositionCode).filter(DispositionCode.company_id == current_user.company_id,
                                             DispositionCode.is_active.is_(True)).order_by(DispositionCode.name).all()
    return {"items": [_row(i) for i in items]}


# ------------------------------------------------------------------ shifts

def _save_assignments(db: Session, shift: Shift, agents: List[int], supervisors: List[int]):
    db.query(ShiftAssignment).filter(ShiftAssignment.shift_id == shift.id).delete()
    for uid in agents:
        db.add(ShiftAssignment(shift_id=shift.id, user_id=uid, role="agent"))
    for uid in supervisors:
        if uid not in agents:
            db.add(ShiftAssignment(shift_id=shift.id, user_id=uid, role="supervisor"))


@router.get("/shifts")
def list_shifts(db: Session = Depends(get_db), current_user: User = Depends(READ)):
    shifts = db.query(Shift).filter(Shift.company_id == current_user.company_id).order_by(Shift.name).all()
    return {"shifts": [_shift_out(db, s) for s in shifts]}


@router.post("/shifts")
def create_shift(data: ShiftIn, db: Session = Depends(get_db), current_user: User = Depends(MANAGE)):
    agents = _company_users(db, current_user.company_id, data.agent_user_ids)
    sups = _company_users(db, current_user.company_id, data.supervisor_user_ids)
    s = Shift(company_id=current_user.company_id, name=data.name, timezone=data.timezone,
              schedule=[x.model_dump() for x in data.schedule], is_active=data.is_active)
    db.add(s)
    db.flush()
    _save_assignments(db, s, agents, sups)
    log_action(db, current_user.company_id, current_user.id, "shift.created", entity_type="shift", entity_id=s.id, entity_name=s.name)
    db.commit()
    return _shift_out(db, s)


@router.put("/shifts/{shift_id}")
def update_shift(shift_id: int, data: ShiftIn, db: Session = Depends(get_db), current_user: User = Depends(MANAGE)):
    s = _get(db, Shift, current_user.company_id, shift_id)
    agents = _company_users(db, current_user.company_id, data.agent_user_ids)
    sups = _company_users(db, current_user.company_id, data.supervisor_user_ids)
    s.name, s.timezone, s.is_active = data.name, data.timezone, data.is_active
    s.schedule = [x.model_dump() for x in data.schedule]
    _save_assignments(db, s, agents, sups)
    log_action(db, current_user.company_id, current_user.id, "shift.updated", entity_type="shift", entity_id=s.id,
               entity_name=s.name, changes=data.model_dump())
    db.commit()
    return _shift_out(db, s)


@router.delete("/shifts/{shift_id}")
def delete_shift(shift_id: int, db: Session = Depends(get_db), current_user: User = Depends(MANAGE)):
    s = _get(db, Shift, current_user.company_id, shift_id)
    log_action(db, current_user.company_id, current_user.id, "shift.deleted", entity_type="shift", entity_id=s.id, entity_name=s.name)
    db.delete(s)
    db.commit()
    return {"ok": True}


# ------------------------------------------------------------------ extensions + full directory

@router.get("/extensions")
def list_extensions(db: Session = Depends(get_db), current_user: User = Depends(READ)):
    rows = db.query(Extension).filter(Extension.company_id == current_user.company_id).order_by(Extension.extension).all()
    return {"items": [_row(r) for r in rows]}


@router.put("/extensions")
def set_extension(data: ExtensionIn, db: Session = Depends(get_db), current_user: User = Depends(MANAGE)):
    _company_users(db, current_user.company_id, [data.user_id])
    row = db.query(Extension).filter(Extension.user_id == data.user_id).first()
    if row:
        row.extension = data.extension
    else:
        row = Extension(company_id=current_user.company_id, user_id=data.user_id, extension=data.extension)
        db.add(row)
    log_action(db, current_user.company_id, current_user.id, "extension.set", entity_type="user",
               entity_id=data.user_id, changes={"extension": data.extension})
    _commit(db, "This extension")
    return _row(row)


@router.delete("/extensions/{user_id}")
def delete_extension(user_id: int, db: Session = Depends(get_db), current_user: User = Depends(MANAGE)):
    db.query(Extension).filter(Extension.user_id == user_id, Extension.company_id == current_user.company_id).delete()
    db.commit()
    return {"ok": True}


@router.get("/phone-directory")
def phone_directory(q: Optional[str] = None, db: Session = Depends(get_db),
                    current_user: User = Depends(require_permission("conversation:read"))):
    """Searchable directory for agents (FR-CC-032): people + extensions + states, queues, entities, external numbers."""
    cid = current_user.company_id
    term = (q or "").strip().lower()
    match = lambda *parts: not term or any(term in (p or "").lower() for p in parts)  # noqa: E731
    exts = {e.user_id: e.extension for e in db.query(Extension).filter(Extension.company_id == cid).all()}
    states = {s.user_id: s.state for s in db.query(AgentState).filter(AgentState.company_id == cid).all()}
    people = []
    for u in db.query(User).filter(User.company_id == cid, User.is_active.is_(True)).all():
        name = " ".join(p for p in [u.first_name, u.last_name] if p) or u.email
        if match(name, u.email, exts.get(u.id)):
            people.append({"user_id": u.id, "name": name, "extension": exts.get(u.id), "state": states.get(u.id, "logged_out")})
    queues = [{"id": x.id, "name": x.name, "is_open": x.is_open, "is_supervisor_queue": x.is_supervisor_queue}
              for x in db.query(CallQueue).filter(CallQueue.company_id == cid).all() if match(x.name)]
    entries = [_row(x) for x in db.query(DirectoryEntry).filter(DirectoryEntry.company_id == cid).all()
               if match(x.name, x.number, x.notes)]
    return {"people": sorted(people, key=lambda p: p["name"].lower()), "queues": queues, "entries": entries}



# ------------------------------------------------------------------ reports (RPT-01..10)

def _can(user: User, perm: str) -> bool:
    return user.is_super_admin or perm in {p.name for p in (user.role.permissions if user.role else [])}


@router.get("/reports")
def list_reports(current_user: User = Depends(require_permission("conversation:read"))):
    return {"reports": [{"name": n, "code": code, "title": fn.__doc__.split(":", 1)[-1].strip().split(".")[0] if fn.__doc__ else n}
                        for n, (code, fn) in cc_report_service.REPORTS.items()]}


@router.get("/reports/{name}")
def run_report(name: str, date_from: Optional[str] = None, date_to: Optional[str] = None, queue_id: Optional[int] = None,
               agent_id: Optional[int] = None, direction: Optional[str] = None, format: str = "json",
               db: Session = Depends(get_db), current_user: User = Depends(require_permission("conversation:read"))):
    if name not in cc_report_service.REPORTS:
        raise HTTPException(status_code=404, detail="Unknown report")
    # data scope (FR-DASH-005): without supervision rights an agent only sees their own figures
    if not _can(current_user, "calls:supervise"):
        agent_id = current_user.id
    try:
        f = cc_report_service.Filters(current_user.company_id, date_from, date_to, queue_id, agent_id, direction)
    except ValueError:
        raise HTTPException(status_code=400, detail="Dates must be YYYY-MM-DD")
    report = cc_report_service.run(db, name, f)
    if format == "json":
        return report
    if not _can(current_user, "reports:export"):  # export is a separate permission
        raise HTTPException(status_code=403, detail="Requires 'reports:export'")
    log_action(db, current_user.company_id, current_user.id, "report.exported", entity_type="report", entity_name=name,
               changes={"format": format, "from": f.start.date().isoformat(), "to": f.end.date().isoformat()})
    db.commit()
    filename = f"{report['code']}-{name}-{f.start.date()}-{f.end.date()}"
    if format == "csv":
        import csv, io
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=report["columns"], extrasaction="ignore")
        w.writeheader()
        w.writerows(report["rows"])
        return Response(buf.getvalue(), media_type="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="{filename}.csv"'})
    if format == "xlsx":
        import io
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.title = report["code"]
        ws.append([report["title"], f"{f.start.date()} – {f.end.date()}", f"generated {report['generated_at'][:19]}"])
        ws.append([])
        ws.append(report["columns"])
        for row in report["rows"]:
            ws.append([row.get(c) for c in report["columns"]])
        out = io.BytesIO()
        wb.save(out)
        return Response(out.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f'attachment; filename="{filename}.xlsx"'})
    raise HTTPException(status_code=400, detail="format must be json, csv or xlsx")


# ------------------------------------------------------------------ quality evaluation (FR-CC-053, RPT-09)

EVALUATE = require_permission("calls:evaluate")


class Criterion(BaseModel):
    key: str = Field(..., pattern=r"^[a-z0-9_]{1,40}$")
    label: str = Field(..., min_length=1, max_length=128)
    weight: float = Field(1, gt=0, le=100)


class QaFormIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    criteria: List[Criterion]
    pass_score: int = Field(70, ge=0, le=100)
    is_active: bool = True


class SampleIn(BaseModel):
    form_id: int
    count: Optional[int] = Field(None, ge=1, le=200)
    percent: Optional[float] = Field(None, gt=0, le=100)
    agent_id: Optional[int] = None
    queue_id: Optional[int] = None
    disposition_code_id: Optional[int] = None
    min_talk_seconds: Optional[int] = None
    days: int = Field(7, ge=1, le=90)


class EvaluateIn(BaseModel):
    scores: dict
    notes: Optional[str] = None
    improvement_plan: Optional[str] = None


@router.get("/qa/forms")
def list_qa_forms(db: Session = Depends(get_db), current_user: User = Depends(EVALUATE)):
    return {"items": [_row(x) for x in db.query(QaForm).filter(QaForm.company_id == current_user.company_id).order_by(QaForm.name)]}


@router.post("/qa/forms")
def create_qa_form(data: QaFormIn, db: Session = Depends(get_db), current_user: User = Depends(EVALUATE)):
    form = QaForm(company_id=current_user.company_id, name=data.name, pass_score=data.pass_score, is_active=data.is_active,
                  criteria=[c.model_dump() for c in data.criteria])
    db.add(form)
    db.commit()
    return _row(form)


@router.put("/qa/forms/{form_id}")
def update_qa_form(form_id: int, data: QaFormIn, db: Session = Depends(get_db), current_user: User = Depends(EVALUATE)):
    form = _get(db, QaForm, current_user.company_id, form_id)
    form.name, form.pass_score, form.is_active = data.name, data.pass_score, data.is_active
    form.criteria = [c.model_dump() for c in data.criteria]
    db.commit()
    return _row(form)


@router.post("/qa/sample")
def qa_sample(data: SampleIn, db: Session = Depends(get_db), current_user: User = Depends(EVALUATE)):
    try:
        evals = qa_retention_service.sample_calls(db, current_user.company_id, evaluator_id=current_user.id,
                                                  **data.model_dump())
    except qa_retention_service.QaError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"created": len(evals), "batch": evals[0].sample_batch if evals else None}


@router.get("/qa/evaluations")
def list_evaluations(status: Optional[str] = None, db: Session = Depends(get_db), current_user: User = Depends(EVALUATE)):
    q = db.query(QaEvaluation).filter(QaEvaluation.company_id == current_user.company_id)
    if status:
        q = q.filter(QaEvaluation.status == status)
    return {"items": [_row(e) for e in q.order_by(QaEvaluation.created_at.desc()).limit(300)]}


@router.put("/qa/evaluations/{eval_id}")
def complete_evaluation(eval_id: int, data: EvaluateIn, db: Session = Depends(get_db), current_user: User = Depends(EVALUATE)):
    ev = _get(db, QaEvaluation, current_user.company_id, eval_id)
    try:
        ev = qa_retention_service.complete(db, ev, current_user.id, data.scores, data.notes, data.improvement_plan)
    except qa_retention_service.QaError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _row(ev)



# ------------------------------------------------------------------ SIP phone accounts (Kamailio registrar)

class SipAccountIn(BaseModel):
    user_id: int
    username: str = Field(..., pattern=r"^[A-Za-z0-9._+-]{2,32}$")
    password: Optional[str] = Field(None, min_length=8, max_length=128)  # required when creating; empty keeps it
    enabled: bool = True


def _sip_out(a: SipAccount, names: dict) -> dict:
    return {"id": a.id, "user_id": a.user_id, "user": names.get(a.user_id), "username": a.username,
            "enabled": a.enabled, "realm": a.realm, "updated_at": a.updated_at.isoformat() if a.updated_at else None}


@router.get("/sip-accounts")
def list_sip_accounts(db: Session = Depends(get_db), current_user: User = Depends(READ)):
    from app.core.config import settings
    names = {u.id: (" ".join(x for x in [u.first_name, u.last_name] if x) or u.email)
             for u in db.query(User).filter(User.company_id == current_user.company_id).all()}
    rows = db.query(SipAccount).filter(SipAccount.company_id == current_user.company_id).order_by(SipAccount.username).all()
    return {"items": [_sip_out(a, names) for a in rows],
            "server": {"address": settings.TELEPHONY_SIP_REGISTRAR_ADDRESS, "realm": settings.TELEPHONY_SIP_REALM,
                       "transports": ["UDP", "TCP"]}}


@router.put("/sip-accounts")
def set_sip_account(data: SipAccountIn, db: Session = Depends(get_db), current_user: User = Depends(MANAGE)):
    """Create or update a user's SIP login. The password is stored only as the SIP digest hash (HA1)."""
    import hashlib
    from app.core.config import settings

    _company_users(db, current_user.company_id, [data.user_id])
    realm = settings.TELEPHONY_SIP_REALM
    account = db.query(SipAccount).filter(SipAccount.user_id == data.user_id).first()
    taken = db.query(SipAccount.id).filter(SipAccount.username == data.username,
                                           SipAccount.user_id != data.user_id).first()
    if taken:
        raise HTTPException(status_code=409, detail="This SIP username is already used")
    if account is None and not data.password:
        raise HTTPException(status_code=400, detail="Set a password for the new SIP account")
    if account is not None and account.username != data.username and not data.password:
        raise HTTPException(status_code=400, detail="Changing the username requires setting the password again")
    if account is None:
        account = SipAccount(company_id=current_user.company_id, user_id=data.user_id)
        db.add(account)
    account.username, account.enabled = data.username, data.enabled
    if data.password:
        account.ha1 = hashlib.md5(f"{data.username}:{realm}:{data.password}".encode()).hexdigest()
        account.realm = realm
    log_action(db, current_user.company_id, current_user.id, "sip_account.set", entity_type="user",
               entity_id=data.user_id, changes={"username": data.username, "enabled": data.enabled,
                                                "password_changed": bool(data.password)})
    _commit(db, "This SIP account")
    names = {data.user_id: None}
    return _sip_out(account, names)


@router.delete("/sip-accounts/{user_id}")
def delete_sip_account(user_id: int, db: Session = Depends(get_db), current_user: User = Depends(MANAGE)):
    account = db.query(SipAccount).filter(SipAccount.user_id == user_id, SipAccount.company_id == current_user.company_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="No SIP account for this user")
    log_action(db, current_user.company_id, current_user.id, "sip_account.deleted", entity_type="user",
               entity_id=user_id, entity_name=account.username)
    db.delete(account)
    db.commit()
    return {"ok": True}
