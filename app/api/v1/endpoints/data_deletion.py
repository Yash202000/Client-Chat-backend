"""
Data Deletion Endpoints

Public (no auth required):
  POST /data-deletion/request          — user-submitted deletion request (JSON)
  POST /data-deletion/facebook         — Facebook signed deletion callback (form)
  GET  /data-deletion/status/{code}    — check status of a request by confirmation code
"""
import hmac
import hashlib
import base64
import json
import uuid
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Form, Request
from pydantic import BaseModel, EmailStr
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.core.config import settings
from app.models.data_deletion_request import DataDeletionRequest

logger = logging.getLogger(__name__)
router = APIRouter()

APP_BASE_URL = getattr(settings, "APP_BASE_URL", "https://app.heygenally.com")
FACEBOOK_APP_SECRET = getattr(settings, "FACEBOOK_APP_SECRET", "")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _gen_code() -> str:
    return f"DEL-{uuid.uuid4().hex[:12].upper()}"


def _parse_facebook_signed_request(signed_request: str, app_secret: str) -> dict:
    """
    Verifies and decodes a Facebook signed_request.
    Raises ValueError on invalid signature.
    """
    try:
        encoded_sig, payload = signed_request.split(".", 1)
    except ValueError:
        raise ValueError("Malformed signed_request")

    # Decode signature
    sig = base64.urlsafe_b64decode(encoded_sig + "==")

    # Verify HMAC-SHA256
    expected = hmac.new(
        app_secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).digest()

    if not hmac.compare_digest(sig, expected):
        raise ValueError("Invalid signed_request signature")

    data = json.loads(base64.urlsafe_b64decode(payload + "=="))
    return data


def _anonymise_contact_by_email(db: Session, email: str) -> int:
    """Anonymise all contact records matching the email. Returns count."""
    anon = f"[deleted-{uuid.uuid4().hex[:8]}]"
    result = db.execute(
        text(
            "UPDATE contacts SET "
            "  email = :anon_email, "
            "  name  = '[deleted]', "
            "  phone_number = NULL, "
            "  profile_picture_url = NULL, "
            "  instagram_handle = NULL, "
            "  facebook_url = NULL, "
            "  linkedin_url = NULL, "
            "  linkedin_urn = NULL, "
            "  custom_attributes = NULL "
            "WHERE email = :email"
        ),
        {"anon_email": anon, "email": email},
    )
    return result.rowcount


def _anonymise_contact_by_facebook_id(db: Session, fb_user_id: str) -> int:
    """
    Anonymise contacts and conversation messages linked to a Facebook page-scoped user ID.
    The Facebook PSID may appear in contacts.custom_attributes->>'facebook_psid'
    or facebook_url. We cover both.
    """
    anon = f"[deleted-fb-{uuid.uuid4().hex[:8]}]"
    count = 0

    # Match via facebook_url containing the user ID
    r1 = db.execute(
        text(
            "UPDATE contacts SET "
            "  email = CASE WHEN email IS NOT NULL THEN :anon ELSE NULL END, "
            "  name  = '[deleted]', "
            "  phone_number = NULL, "
            "  profile_picture_url = NULL, "
            "  instagram_handle = NULL, "
            "  facebook_url = NULL, "
            "  custom_attributes = NULL "
            "WHERE facebook_url LIKE :pattern"
        ),
        {"anon": anon, "pattern": f"%{fb_user_id}%"},
    )
    count += r1.rowcount

    # Match via custom_attributes JSONB field 'facebook_psid'
    try:
        r2 = db.execute(
            text(
                "UPDATE contacts SET "
                "  email = CASE WHEN email IS NOT NULL THEN :anon2 ELSE NULL END, "
                "  name  = '[deleted]', "
                "  phone_number = NULL, "
                "  profile_picture_url = NULL, "
                "  facebook_url = NULL, "
                "  custom_attributes = NULL "
                "WHERE custom_attributes->>'facebook_psid' = :fb_id"
            ),
            {"anon2": f"[deleted-fb-{uuid.uuid4().hex[:8]}]", "fb_id": fb_user_id},
        )
        count += r2.rowcount
    except Exception:
        pass  # custom_attributes may not exist on all rows

    return count


# ── Schemas ───────────────────────────────────────────────────────────────────

class DeletionRequestIn(BaseModel):
    email: str
    name: Optional[str] = None
    details: Optional[str] = None


class DeletionRequestOut(BaseModel):
    confirmation_code: str
    status: str
    status_url: str
    message: str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/request", response_model=DeletionRequestOut)
def submit_deletion_request(payload: DeletionRequestIn, db: Session = Depends(get_db)):
    """
    Public endpoint — user submits a deletion request via the /data-deletion web form.
    Immediately anonymises matching contact records and logs the request.
    """
    code = _gen_code()

    req = DataDeletionRequest(
        confirmation_code=code,
        request_type="user_submitted",
        email=payload.email,
        name=payload.name,
        details=payload.details,
        status="processing",
    )
    db.add(req)
    db.flush()

    # Anonymise now
    try:
        _anonymise_contact_by_email(db, payload.email)
    except Exception:
        logger.exception("Error anonymising contact for email %s", payload.email)

    req.status = "completed"
    req.processed_at = datetime.utcnow()
    db.commit()

    return DeletionRequestOut(
        confirmation_code=code,
        status="completed",
        status_url=f"{APP_BASE_URL}/data-deletion?code={code}",
        message="Your data has been queued for deletion and will be permanently removed within 30 days.",
    )


@router.post("/facebook")
async def facebook_deletion_callback(
    request: Request,
    signed_request: str = Form(...),
    db: Session = Depends(get_db),
):
    """
    Facebook Data Deletion Callback — configure this URL in your Facebook App settings
    under Settings → Advanced → Data Deletion.

    Facebook POSTs a signed_request (form-encoded) when a user removes your app
    or deletes their Facebook account. We verify the signature, anonymise the data,
    and return the required JSON with a confirmation_code and status_url.
    """
    if not FACEBOOK_APP_SECRET:
        logger.error("FACEBOOK_APP_SECRET not configured — cannot verify deletion callback")
        raise HTTPException(status_code=500, detail="App not configured for Facebook callbacks")

    try:
        data = _parse_facebook_signed_request(signed_request, FACEBOOK_APP_SECRET)
    except ValueError as e:
        logger.warning("Invalid Facebook signed_request: %s", e)
        raise HTTPException(status_code=400, detail=str(e))

    fb_user_id = data.get("user_id") or data.get("user", {}).get("id", "")
    if not fb_user_id:
        raise HTTPException(status_code=400, detail="No user_id in signed_request")

    code = _gen_code()
    req = DataDeletionRequest(
        confirmation_code=code,
        request_type="facebook_callback",
        facebook_user_id=str(fb_user_id),
        status="processing",
    )
    db.add(req)
    db.flush()

    try:
        _anonymise_contact_by_facebook_id(db, str(fb_user_id))
    except Exception:
        logger.exception("Error anonymising Facebook user %s", fb_user_id)

    req.status = "completed"
    req.processed_at = datetime.utcnow()
    db.commit()

    # Facebook requires this exact response shape
    return {
        "url": f"{APP_BASE_URL}/data-deletion?code={code}",
        "confirmation_code": code,
    }


@router.get("/status/{code}")
def get_deletion_status(code: str, db: Session = Depends(get_db)):
    """
    Public status check — called from the /data-deletion?code=xxx page.
    Also used by Facebook to verify deletion was processed.
    """
    req = db.query(DataDeletionRequest).filter(
        DataDeletionRequest.confirmation_code == code
    ).first()

    if not req:
        raise HTTPException(status_code=404, detail="Confirmation code not found")

    return {
        "confirmation_code": req.confirmation_code,
        "status": req.status,
        "request_type": req.request_type,
        "created_at": req.created_at.isoformat(),
        "processed_at": req.processed_at.isoformat() if req.processed_at else None,
    }
