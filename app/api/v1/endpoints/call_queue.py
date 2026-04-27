from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime
import logging

from app.core.dependencies import get_db, get_current_active_user
from app.models.call_queue import CallQueueEntry
from app.models.user import User

router = APIRouter()
logger = logging.getLogger(__name__)


# ── Schemas ────────────────────────────────────────────────────────────────────

class QueueEntryOut(BaseModel):
    id: int
    call_sid: str
    source: str
    caller_number: str
    caller_name: Optional[str]
    status: str
    priority: int
    required_skill: Optional[str] = None
    voicemail_url: Optional[str] = None
    overflow_at: Optional[datetime] = None
    entered_at: datetime
    ringing_at: Optional[datetime]
    connected_at: Optional[datetime]
    ended_at: Optional[datetime]
    estimated_wait_secs: Optional[int]
    assigned_agent_id: Optional[int]
    wait_secs: Optional[int] = None   # computed

    class Config:
        from_attributes = True


class QueueEntryCreate(BaseModel):
    call_sid: str
    source: str = "twilio"
    caller_number: str
    caller_name: Optional[str] = None
    session_id: Optional[str] = None
    contact_id: Optional[int] = None
    priority: int = 0
    required_skill: Optional[str] = None


class SkillUpdate(BaseModel):
    required_skill: Optional[str] = None


class SLAConfig(BaseModel):
    sla_seconds: int = 120
    overflow_action: str = "voicemail"  # voicemail | drop | escalate
    escalate_after_seconds: int = 60


# ── Helpers ────────────────────────────────────────────────────────────────────

def _enrich(entry: CallQueueEntry) -> dict:
    d = {c.name: getattr(entry, c.name) for c in entry.__table__.columns}
    now = datetime.utcnow()
    d["wait_secs"] = int((now - entry.entered_at).total_seconds()) if entry.entered_at else None
    return d


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/", response_model=List[QueueEntryOut])
def list_queue(
    status: Optional[str] = "waiting",
    skill: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """List call queue entries. Default: only waiting calls. Optional skill filter."""
    q = db.query(CallQueueEntry).filter(
        CallQueueEntry.company_id == current_user.company_id
    )
    if status:
        q = q.filter(CallQueueEntry.status == status)
    if skill:
        q = q.filter(CallQueueEntry.required_skill == skill)
    entries = q.order_by(CallQueueEntry.priority.desc(), CallQueueEntry.entered_at.asc()).all()
    return [_enrich(e) for e in entries]


@router.post("/", response_model=QueueEntryOut)
def create_queue_entry(
    payload: QueueEntryCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Manually enqueue a call (also called internally by voice webhooks)."""
    entry = CallQueueEntry(
        company_id=current_user.company_id,
        **payload.model_dump(),
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return _enrich(entry)


@router.patch("/{entry_id}/skill", response_model=QueueEntryOut)
def set_queue_entry_skill(
    entry_id: int,
    payload: SkillUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Set or clear the required_skill on a queue entry."""
    entry = db.query(CallQueueEntry).filter(
        CallQueueEntry.id == entry_id,
        CallQueueEntry.company_id == current_user.company_id,
    ).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Queue entry not found")
    entry.required_skill = payload.required_skill
    db.commit()
    db.refresh(entry)
    return _enrich(entry)


@router.post("/{entry_id}/accept", response_model=QueueEntryOut)
def accept_queue_entry(
    entry_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Agent accepts a queued call — marks it ringing, assigns to this agent, and bridges via Twilio."""
    entry = db.query(CallQueueEntry).filter(
        CallQueueEntry.id == entry_id,
        CallQueueEntry.company_id == current_user.company_id,
        CallQueueEntry.status == "waiting",
    ).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Queue entry not found or no longer waiting")

    entry.status = "ringing"
    entry.ringing_at = datetime.utcnow()
    entry.assigned_agent_id = current_user.id
    db.commit()
    db.refresh(entry)
    logger.info(f"[Queue] Agent {current_user.id} accepted call {entry.call_sid}")

    # For Twilio voice calls, redirect the live call to the agent's browser client
    if entry.source == "twilio":
        try:
            from app.models.integration import Integration
            from app.services import integration_service
            from twilio.rest import Client as TwilioClient

            integration = db.query(Integration).filter(
                Integration.company_id == current_user.company_id,
                Integration.type == "twilio_voice",
                Integration.is_active == True,
            ).first()
            if integration:
                creds = integration_service.get_decrypted_credentials(integration)
                twilio_client = TwilioClient(creds["account_sid"], creds["auth_token"])
                agent_identity = f"agent_{current_user.id}"
                twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say>Connecting you to an agent now.</Say>
  <Dial><Client>{agent_identity}</Client></Dial>
</Response>"""
                twilio_client.calls(entry.call_sid).update(twiml=twiml)
                entry.status = "connected"
                entry.connected_at = datetime.utcnow()
                db.commit()
                db.refresh(entry)
                logger.info(f"[Queue] Bridged {entry.call_sid} to {agent_identity}")
        except Exception as bridge_err:
            logger.warning(f"[Queue] Could not bridge call {entry.call_sid}: {bridge_err}")

    return _enrich(entry)


@router.post("/{entry_id}/connected", response_model=QueueEntryOut)
def mark_connected(
    entry_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Mark the call as actually connected (bridge established)."""
    entry = db.query(CallQueueEntry).filter(
        CallQueueEntry.id == entry_id,
        CallQueueEntry.company_id == current_user.company_id,
    ).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Queue entry not found")
    entry.status = "connected"
    entry.connected_at = datetime.utcnow()
    db.commit()
    db.refresh(entry)
    return _enrich(entry)


@router.post("/{entry_id}/abandon", response_model=QueueEntryOut)
def abandon_queue_entry(
    entry_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Mark a queued call as abandoned (caller hung up while waiting)."""
    entry = db.query(CallQueueEntry).filter(
        CallQueueEntry.id == entry_id,
        CallQueueEntry.company_id == current_user.company_id,
    ).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Queue entry not found")
    entry.status = "abandoned"
    entry.ended_at = datetime.utcnow()
    db.commit()
    db.refresh(entry)
    return _enrich(entry)


@router.get("/stats")
def queue_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Real-time queue stats for the dashboard."""
    base = db.query(CallQueueEntry).filter(
        CallQueueEntry.company_id == current_user.company_id
    )
    waiting = base.filter(CallQueueEntry.status == "waiting").all()
    now = datetime.utcnow()

    wait_times = [
        int((now - e.entered_at).total_seconds()) for e in waiting if e.entered_at
    ]

    return {
        "waiting": len(waiting),
        "ringing": base.filter(CallQueueEntry.status == "ringing").count(),
        "connected": base.filter(CallQueueEntry.status == "connected").count(),
        "avg_wait_secs": int(sum(wait_times) / len(wait_times)) if wait_times else 0,
        "max_wait_secs": max(wait_times) if wait_times else 0,
    }


# ── SLA Config (Item 8) ───────────────────────────────────────────────────────

# In-memory SLA config store keyed by company_id (simple approach)
_sla_configs: dict = {}

_DEFAULT_SLA = {
    "sla_seconds": 120,
    "overflow_action": "voicemail",
    "escalate_after_seconds": 60,
}


@router.get("/sla-config")
def get_sla_config(
    current_user: User = Depends(get_current_active_user),
):
    """Return current SLA settings for the company."""
    return _sla_configs.get(current_user.company_id, _DEFAULT_SLA.copy())


@router.put("/sla-config")
def update_sla_config(
    payload: SLAConfig,
    current_user: User = Depends(get_current_active_user),
):
    """Update SLA settings for the company."""
    _sla_configs[current_user.company_id] = payload.model_dump()
    return _sla_configs[current_user.company_id]


# ── Voicemail TwiML Endpoints (Item 2) ────────────────────────────────────────

@router.post("/twiml/voicemail")
async def twiml_voicemail(request: Request, db: Session = Depends(get_db)):
    """TwiML endpoint — records a voicemail when SLA is breached."""
    form_data = await request.form()
    call_sid = form_data.get("CallSid", "")

    from app.core.config import settings
    public_host = getattr(settings, 'PUBLIC_HOST', None) or request.headers.get('Host', 'localhost')
    callback_url = f"https://{public_host}/api/v1/voice/queue/twiml/voicemail-complete"

    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say>All agents are currently busy. Please leave a message after the beep and we will call you back.</Say>
  <Record maxLength="120" action="{callback_url}" recordingStatusCallback="{callback_url}" />
  <Say>Thank you. Goodbye.</Say>
  <Hangup/>
</Response>"""
    return Response(content=twiml, media_type="application/xml")


@router.post("/twiml/voicemail-complete")
async def twiml_voicemail_complete(request: Request, db: Session = Depends(get_db)):
    """TwiML status callback — saves the recording URL to the queue entry."""
    form_data = await request.form()
    call_sid = form_data.get("CallSid", "")
    recording_url = form_data.get("RecordingUrl", "")

    if call_sid and recording_url:
        entry = db.query(CallQueueEntry).filter(
            CallQueueEntry.call_sid == call_sid
        ).first()
        if entry:
            entry.voicemail_url = recording_url
            db.commit()
            logger.info(f"[Voicemail] Saved recording for {call_sid}: {recording_url}")

    return Response(
        content='<?xml version="1.0" encoding="UTF-8"?><Response></Response>',
        media_type="application/xml",
    )
