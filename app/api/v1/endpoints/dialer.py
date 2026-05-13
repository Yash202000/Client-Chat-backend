"""
Predictive Dialer endpoints.

Simple dialer that takes a list of contact IDs and calls each in sequence.
Sessions stored in-memory (no DB model needed for MVP).
"""
import asyncio
import logging
from datetime import datetime
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, get_current_active_user
from app.models.user import User
from app.models.contact import Contact
from app.models.integration import Integration
from app.models.twilio_phone_number import TwilioPhoneNumber
from app.services import integration_service

router = APIRouter()
logger = logging.getLogger(__name__)

# ── In-memory session store ────────────────────────────────────────────────────
# { session_id: DialerSessionState }

_sessions: Dict[int, Dict[str, Any]] = {}
_session_counter = 0


# ── Schemas ────────────────────────────────────────────────────────────────────

class DialerSessionCreate(BaseModel):
    contact_ids: List[int]
    agent_user_id: int
    message_template: Optional[str] = None   # spoken when answered


class DialerSessionOut(BaseModel):
    id: int
    status: str          # pending | running | paused | completed | stopped
    total: int
    dialed: int
    answered: int
    failed: int
    contact_ids: List[int]
    message_template: Optional[str]
    created_at: str
    results: List[Dict[str, Any]]


# ── Helpers ────────────────────────────────────────────────────────────────────

def _session_out(s: Dict[str, Any]) -> DialerSessionOut:
    return DialerSessionOut(
        id=s["id"],
        status=s["status"],
        total=s["total"],
        dialed=s["dialed"],
        answered=s["answered"],
        failed=s["failed"],
        contact_ids=s["contact_ids"],
        message_template=s["message_template"],
        created_at=s["created_at"],
        results=s["results"],
    )


def _get_twilio_client_for_company(db: Session, company_id: int):
    integration = db.query(Integration).filter(
        Integration.company_id == company_id,
        Integration.type == "twilio_voice",
        Integration.is_active == True,
    ).first()
    if not integration:
        return None, None, None
    creds = integration_service.get_decrypted_credentials(integration)
    try:
        from twilio.rest import Client as TwilioClient
        client = TwilioClient(creds["account_sid"], creds["auth_token"])
    except Exception:
        return None, None, None
    phone = db.query(TwilioPhoneNumber).filter(
        TwilioPhoneNumber.company_id == company_id,
        TwilioPhoneNumber.is_active == True,
    ).first()
    from_number = phone.phone_number if phone else creds.get("phone_number", "")
    return client, creds, from_number


# ── Background dialing task ────────────────────────────────────────────────────

async def _run_dialer(session_id: int, db_factory):
    """Background asyncio task that calls contacts in sequence."""
    s = _sessions.get(session_id)
    if not s:
        return

    from app.core.config import settings

    db: Session = db_factory()
    try:
        company_id = s["company_id"]
        twilio_client, creds, from_number = _get_twilio_client_for_company(db, company_id)
        if not twilio_client:
            s["status"] = "stopped"
            logger.warning(f"[Dialer] No Twilio client for company {company_id}")
            return

        public_host = getattr(settings, "PUBLIC_HOST", "localhost")
        twiml_url = f"https://{public_host}/api/v1/dialer/twiml/{session_id}"

        for contact_id in s["contact_ids"]:
            if s["status"] != "running":
                break

            contact = db.query(Contact).filter(
                Contact.id == contact_id,
                Contact.company_id == company_id,
            ).first()

            result: Dict[str, Any] = {
                "contact_id": contact_id,
                "phone_number": contact.phone_number if contact else None,
                "name": contact.name if contact else None,
                "outcome": "skipped",
                "call_sid": None,
                "dialed_at": datetime.utcnow().isoformat(),
            }

            if not contact or not contact.phone_number:
                result["outcome"] = "no_phone"
                s["results"].append(result)
                s["dialed"] += 1
                continue

            try:
                call = twilio_client.calls.create(
                    to=contact.phone_number,
                    from_=from_number,
                    url=twiml_url,
                    method="GET",
                )
                result["call_sid"] = call.sid
                result["outcome"] = "dialing"
                s["dialed"] += 1
                logger.info(f"[Dialer] Dialed {contact.phone_number}: {call.sid}")

                # Poll briefly for call completion
                for _ in range(15):
                    await asyncio.sleep(2)
                    if s["status"] != "running":
                        break
                    try:
                        updated = twilio_client.calls(call.sid).fetch()
                        if updated.status in ("completed", "busy", "no-answer", "failed", "canceled"):
                            result["outcome"] = updated.status
                            if updated.status == "completed":
                                s["answered"] += 1
                            else:
                                s["failed"] += 1
                            break
                    except Exception:
                        logger.exception("Unexpected error")
                else:
                    # timed out polling
                    if result["outcome"] == "dialing":
                        result["outcome"] = "timeout"
                        s["failed"] += 1

            except Exception as e:
                logger.warning(f"[Dialer] Failed to call {contact.phone_number}: {e}")
                result["outcome"] = "error"
                result["error"] = str(e)
                s["failed"] += 1
                s["dialed"] += 1

            s["results"].append(result)
            # Small pause between calls
            await asyncio.sleep(2)

    except Exception as e:
        logger.error(f"[Dialer] Session {session_id} error: {e}", exc_info=True)
    finally:
        db.close()
        if s and s["status"] == "running":
            s["status"] = "completed"
        logger.info(f"[Dialer] Session {session_id} finished")


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/sessions", response_model=DialerSessionOut)
def create_session(
    payload: DialerSessionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Create a new dialer session."""
    global _session_counter
    _session_counter += 1
    sid = _session_counter

    _sessions[sid] = {
        "id": sid,
        "company_id": current_user.company_id,
        "agent_user_id": payload.agent_user_id,
        "contact_ids": payload.contact_ids,
        "message_template": payload.message_template,
        "status": "pending",
        "total": len(payload.contact_ids),
        "dialed": 0,
        "answered": 0,
        "failed": 0,
        "results": [],
        "created_at": datetime.utcnow().isoformat(),
    }
    return _session_out(_sessions[sid])


@router.get("/sessions", response_model=List[DialerSessionOut])
def list_sessions(
    current_user: User = Depends(get_current_active_user),
):
    """List all dialer sessions for this company."""
    company_id = current_user.company_id
    out = [_session_out(s) for s in _sessions.values() if s["company_id"] == company_id]
    return sorted(out, key=lambda x: x.id, reverse=True)


@router.get("/sessions/{session_id}", response_model=DialerSessionOut)
def get_session(
    session_id: int,
    current_user: User = Depends(get_current_active_user),
):
    s = _sessions.get(session_id)
    if not s or s["company_id"] != current_user.company_id:
        raise HTTPException(status_code=404, detail="Dialer session not found")
    return _session_out(s)


@router.post("/sessions/{session_id}/start", response_model=DialerSessionOut)
def start_session(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Start or resume the dialer session."""
    s = _sessions.get(session_id)
    if not s or s["company_id"] != current_user.company_id:
        raise HTTPException(status_code=404, detail="Dialer session not found")
    if s["status"] == "running":
        return _session_out(s)
    s["status"] = "running"

    from app.core.database import SessionLocal
    asyncio.create_task(_run_dialer(session_id, SessionLocal))
    return _session_out(s)


@router.post("/sessions/{session_id}/pause", response_model=DialerSessionOut)
def pause_session(
    session_id: int,
    current_user: User = Depends(get_current_active_user),
):
    """Pause the dialer session (stops placing new calls after current one)."""
    s = _sessions.get(session_id)
    if not s or s["company_id"] != current_user.company_id:
        raise HTTPException(status_code=404, detail="Dialer session not found")
    s["status"] = "paused"
    return _session_out(s)


@router.post("/sessions/{session_id}/stop", response_model=DialerSessionOut)
def stop_session(
    session_id: int,
    current_user: User = Depends(get_current_active_user),
):
    """Stop the dialer session."""
    s = _sessions.get(session_id)
    if not s or s["company_id"] != current_user.company_id:
        raise HTTPException(status_code=404, detail="Dialer session not found")
    s["status"] = "stopped"
    return _session_out(s)


@router.get("/sessions/{session_id}/results")
def session_results(
    session_id: int,
    current_user: User = Depends(get_current_active_user),
):
    """Per-contact outcomes for a dialer session."""
    s = _sessions.get(session_id)
    if not s or s["company_id"] != current_user.company_id:
        raise HTTPException(status_code=404, detail="Dialer session not found")
    return {"session_id": session_id, "results": s["results"]}


# ── TwiML greeting endpoint ────────────────────────────────────────────────────

@router.get("/twiml/{session_id}")
async def dialer_twiml(session_id: int):
    """TwiML greeting for dialer calls — speaks the message_template then hangs up."""
    s = _sessions.get(session_id)
    message = (s or {}).get("message_template") or "Hello! This is an automated call from our team. Thank you for your time. Goodbye."

    # Sanitise basic XML chars
    message = message.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say voice="Polly.Joanna">{message}</Say>
  <Pause length="1"/>
  <Hangup/>
</Response>"""
    return Response(content=twiml, media_type="application/xml")
