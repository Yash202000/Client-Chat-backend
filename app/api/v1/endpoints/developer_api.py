"""
Developer / Public Messaging API

Lets B2B clients send messages from their own apps using an API key.
No session cookie needed — authenticated via 'Authorization: Bearer <api_key>' header.

POST /developer/messages/send      — send whatsapp/sms/email message
POST /developer/verify/send        — send OTP
POST /developer/verify/check       — check OTP
POST /developer/cod/verify         — send COD confirmation
GET  /developer/contacts           — list contacts
POST /developer/contacts           — create/update contact
GET  /developer/usage              — API usage stats for this key
GET  /developer/usage/stats        — usage dashboard stats (session auth)
GET  /developer/usage/logs         — paginated API call logs (session auth)
"""
import logging
from datetime import datetime, timedelta
from typing import Optional, Literal, List
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Query
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
from sqlalchemy import func, Integer

from app.core.dependencies import get_db, get_current_active_user
from app.models.api_key import ApiKey
from app.models.user import User as UserModel
from app.services import api_key_service

router = APIRouter()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Logging helper — call at end of each developer endpoint
# ---------------------------------------------------------------------------

def _log_call(
    db: Session,
    api_key: "ApiKey",
    endpoint: str,
    method: str = "POST",
    status_code: int = 200,
    response_ms: int = None,
):
    from app.models.api_key_log import ApiKeyLog
    try:
        db.add(ApiKeyLog(
            api_key_id=api_key.id,
            company_id=api_key.company_id,
            endpoint=endpoint,
            method=method,
            status_code=status_code,
            response_ms=response_ms,
        ))
        db.commit()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Auth dependency — API key via Bearer token
# ---------------------------------------------------------------------------

def get_api_key_context(
    authorization: str = Header(..., description="Bearer <your_api_key>"),
    db: Session = Depends(get_db),
) -> ApiKey:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization header must be 'Bearer <api_key>'")

    raw_key = authorization[7:].strip()
    api_key = api_key_service.get_api_key_by_key(db, raw_key)

    if not api_key:
        raise HTTPException(status_code=401, detail="Invalid API key.")
    if not api_key.is_active:
        raise HTTPException(status_code=401, detail="API key is disabled.")
    if api_key.expires_at and api_key.expires_at < datetime.utcnow():
        raise HTTPException(status_code=401, detail="API key has expired.")

    # Update last_used_at
    api_key.last_used_at = datetime.utcnow()
    db.commit()

    return api_key


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class SendMessageRequest(BaseModel):
    channel: Literal["whatsapp", "sms", "email"]
    to: str                                # phone (E.164) or email
    message: str
    subject: Optional[str] = None          # email only


class SendMessageResponse(BaseModel):
    success: bool
    channel: str
    to: str
    message_id: Optional[str] = None


class OTPSendRequest(BaseModel):
    channel: Literal["whatsapp", "sms", "email", "voice"]
    recipient: str
    template: Optional[str] = None


class OTPCheckRequest(BaseModel):
    verification_id: str
    code: str


class CODRequest(BaseModel):
    order_id: str
    channel: Literal["whatsapp", "sms"]
    recipient: str
    order_amount: Optional[float] = None
    currency: str = "INR"
    customer_name: Optional[str] = None
    webhook_url: Optional[str] = None


class ContactUpsertRequest(BaseModel):
    phone_number: Optional[str] = None
    email: Optional[str] = None
    name: Optional[str] = None
    lead_source: Optional[str] = None
    tags: Optional[List[str]] = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/messages/send", response_model=SendMessageResponse)
async def send_message(
    body: SendMessageRequest,
    db: Session = Depends(get_db),
    api_key: ApiKey = Depends(get_api_key_context),
):
    """Send a single message via WhatsApp, SMS, or Email."""
    company_id = api_key.company_id

    try:
        if body.channel == "whatsapp":
            from app.services import messaging_service, integration_service
            integration = integration_service.get_integration_by_type_and_company(db, "whatsapp", company_id)
            if not integration:
                raise HTTPException(status_code=400, detail="WhatsApp integration not configured.")
            result = await messaging_service.send_whatsapp_message(
                recipient_phone_number=body.to,
                message_text=body.message,
                integration=integration,
                db=db,
            )
            msg_id = result.get("messages", [{}])[0].get("id")
            _log_call(db, api_key, "/developer/messages/send", "POST", 200)
            return SendMessageResponse(success=True, channel="whatsapp", to=body.to, message_id=msg_id)

        elif body.channel == "sms":
            from app.services import sms_service
            result = sms_service.send_sms(to=body.to, body=body.message, db=db, company_id=company_id)
            _log_call(db, api_key, "/developer/messages/send", "POST", 200)
            return SendMessageResponse(success=True, channel="sms", to=body.to, message_id=result.get("sid"))

        elif body.channel == "email":
            from app.models.company_settings import CompanySettings
            from app.services import email_service

            cs = db.query(CompanySettings).filter(CompanySettings.company_id == company_id).first()
            if not cs or not cs.smtp_host:
                raise HTTPException(status_code=400, detail="SMTP not configured.")

            smtp_config = {
                "host": cs.smtp_host, "port": cs.smtp_port or 587,
                "user": cs.smtp_user, "password": cs.smtp_password,
                "use_tls": cs.smtp_use_tls if cs.smtp_use_tls is not None else True,
            }
            result = await email_service.send_email_smtp(
                to_email=body.to,
                subject=body.subject or "Message",
                text_content=body.message,
                html_content=f"<p>{body.message}</p>",
                from_email=cs.smtp_from_email,
                from_name=cs.smtp_from_name,
                smtp_config=smtp_config,
            )
            _log_call(db, api_key, "/developer/messages/send", "POST", 200)
            return SendMessageResponse(success=True, channel="email", to=body.to, message_id=result.get("message_id"))

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[DevAPI] send_message error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/verify/send")
async def dev_send_otp(
    body: OTPSendRequest,
    db: Session = Depends(get_db),
    api_key: ApiKey = Depends(get_api_key_context),
):
    """Send an OTP via the specified channel."""
    from app.services import otp_service
    try:
        otp = await otp_service.send_otp(
            db=db, company_id=api_key.company_id,
            channel=body.channel, recipient=body.recipient, template=body.template,
        )
        _log_call(db, api_key, "/developer/verify/send", "POST", 200)
        return {
            "verification_id": otp.verification_id,
            "channel": otp.channel.value,
            "expires_at": otp.expires_at.isoformat(),
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/verify/check")
def dev_check_otp(
    body: OTPCheckRequest,
    db: Session = Depends(get_db),
    api_key: ApiKey = Depends(get_api_key_context),
):
    """Validate an OTP code."""
    from app.services import otp_service
    valid, message = otp_service.verify_otp(db, body.verification_id, body.code)
    _log_call(db, api_key, "/developer/verify/check", "POST", 200)
    return {"valid": valid, "message": message}


@router.post("/cod/verify")
async def dev_cod_verify(
    body: CODRequest,
    db: Session = Depends(get_db),
    api_key: ApiKey = Depends(get_api_key_context),
):
    """Send a COD confirmation request."""
    from app.services import cod_service
    try:
        cod = await cod_service.create_cod_verification(
            db=db, company_id=api_key.company_id,
            order_id=body.order_id, channel=body.channel,
            recipient=body.recipient,
            order_amount=body.order_amount,
            currency=body.currency,
            customer_name=body.customer_name,
            webhook_url=body.webhook_url,
        )
        _log_call(db, api_key, "/developer/cod/verify", "POST", 200)
        return {"verification_id": cod.verification_id, "status": cod.status.value, "expires_at": cod.expires_at.isoformat()}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/contacts")
def dev_upsert_contact(
    body: ContactUpsertRequest,
    db: Session = Depends(get_db),
    api_key: ApiKey = Depends(get_api_key_context),
):
    """Create or update a contact by phone or email."""
    from app.models.contact import Contact
    from app.models.tag import Tag

    if not body.phone_number and not body.email:
        raise HTTPException(status_code=400, detail="phone_number or email required.")

    company_id = api_key.company_id
    contact = None

    if body.phone_number:
        contact = db.query(Contact).filter(
            Contact.phone_number == body.phone_number,
            Contact.company_id == company_id,
        ).first()
    if not contact and body.email:
        contact = db.query(Contact).filter(
            Contact.email == body.email,
            Contact.company_id == company_id,
        ).first()

    if not contact:
        contact = Contact(company_id=company_id)
        db.add(contact)

    if body.phone_number: contact.phone_number = body.phone_number
    if body.email: contact.email = body.email
    if body.name: contact.name = body.name
    if body.lead_source: contact.lead_source = body.lead_source

    if body.tags:
        for tag_name in body.tags:
            tag = db.query(Tag).filter(Tag.name == tag_name, Tag.company_id == company_id).first()
            if not tag:
                tag = Tag(name=tag_name, company_id=company_id)
                db.add(tag)
                db.flush()
            if tag not in contact.tags:
                contact.tags.append(tag)

    db.commit()
    db.refresh(contact)
    _log_call(db, api_key, "/developer/contacts", "POST", 200)
    return {"id": contact.id, "name": contact.name, "phone_number": contact.phone_number, "email": contact.email}


@router.get("/usage")
def dev_usage(
    db: Session = Depends(get_db),
    api_key: ApiKey = Depends(get_api_key_context),
):
    """Return basic usage info for this API key."""
    return {
        "api_key_name": api_key.name,
        "company_id": api_key.company_id,
        "created_at": api_key.created_at.isoformat(),
        "last_used_at": api_key.last_used_at.isoformat() if api_key.last_used_at else None,
        "expires_at": api_key.expires_at.isoformat() if api_key.expires_at else None,
        "scopes": api_key.scopes or ["*"],
        "endpoints": [
            "POST /api/v1/developer/messages/send",
            "POST /api/v1/developer/verify/send",
            "POST /api/v1/developer/verify/check",
            "POST /api/v1/developer/cod/verify",
            "POST /api/v1/developer/contacts",
            "GET  /api/v1/developer/usage",
        ],
    }


# ---------------------------------------------------------------------------
# Dashboard stats & logs — authenticated via session (JWT), not API key
# ---------------------------------------------------------------------------

@router.get("/usage/stats")
def dev_usage_stats(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_active_user),
    x_company_id: int = Header(...),
):
    """Return aggregated usage stats for the company's API keys (dashboard view)."""
    from app.models.api_key_log import ApiKeyLog

    company_id = x_company_id
    since = datetime.utcnow() - timedelta(days=days)

    # Base query scoped to company
    base = db.query(ApiKeyLog).filter(
        ApiKeyLog.company_id == company_id,
        ApiKeyLog.created_at >= since,
    )

    total_calls = base.count()
    success_calls = base.filter(ApiKeyLog.status_code < 400).count()
    error_calls = total_calls - success_calls

    avg_ms_result = db.query(func.avg(ApiKeyLog.response_ms)).filter(
        ApiKeyLog.company_id == company_id,
        ApiKeyLog.created_at >= since,
        ApiKeyLog.response_ms.isnot(None),
    ).scalar()
    avg_response_ms = int(avg_ms_result) if avg_ms_result else 0

    # By endpoint
    endpoint_rows = (
        db.query(
            ApiKeyLog.endpoint,
            func.count(ApiKeyLog.id).label("count"),
            func.sum(
                func.cast(ApiKeyLog.status_code >= 400, Integer)
            ).label("errors"),
        )
        .filter(ApiKeyLog.company_id == company_id, ApiKeyLog.created_at >= since)
        .group_by(ApiKeyLog.endpoint)
        .order_by(func.count(ApiKeyLog.id).desc())
        .all()
    )
    by_endpoint = [
        {"endpoint": r.endpoint, "count": r.count, "errors": int(r.errors or 0)}
        for r in endpoint_rows
    ]

    # Daily trend — use date truncation (works for PostgreSQL)
    try:
        daily_rows = (
            db.query(
                func.date_trunc("day", ApiKeyLog.created_at).label("date"),
                func.count(ApiKeyLog.id).label("calls"),
                func.sum(
                    func.cast(ApiKeyLog.status_code >= 400, Integer)
                ).label("errors"),
            )
            .filter(ApiKeyLog.company_id == company_id, ApiKeyLog.created_at >= since)
            .group_by(func.date_trunc("day", ApiKeyLog.created_at))
            .order_by(func.date_trunc("day", ApiKeyLog.created_at))
            .all()
        )
        daily_trend = [
            {
                "date": r.date.strftime("%Y-%m-%d"),
                "calls": r.calls,
                "errors": int(r.errors or 0),
            }
            for r in daily_rows
        ]
    except Exception:
        daily_trend = []

    # Per-key breakdown
    key_rows = (
        db.query(
            ApiKeyLog.api_key_id,
            func.count(ApiKeyLog.id).label("calls"),
            func.max(ApiKeyLog.created_at).label("last_used"),
        )
        .filter(ApiKeyLog.company_id == company_id, ApiKeyLog.created_at >= since)
        .group_by(ApiKeyLog.api_key_id)
        .all()
    )

    # Enrich with key names
    key_ids = [r.api_key_id for r in key_rows]
    keys_map = {}
    if key_ids:
        key_objs = db.query(ApiKey).filter(ApiKey.id.in_(key_ids)).all()
        keys_map = {k.id: k for k in key_objs}

    api_keys_stats = [
        {
            "id": r.api_key_id,
            "name": keys_map[r.api_key_id].name if r.api_key_id in keys_map else "Unknown",
            "calls": r.calls,
            "last_used_at": r.last_used.isoformat() if r.last_used else None,
        }
        for r in key_rows
    ]

    return {
        "total_calls": total_calls,
        "success_calls": success_calls,
        "error_calls": error_calls,
        "avg_response_ms": avg_response_ms,
        "by_endpoint": by_endpoint,
        "daily_trend": daily_trend,
        "api_keys": api_keys_stats,
    }


@router.get("/usage/logs")
def dev_usage_logs(
    days: int = Query(7, ge=1, le=90),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    api_key_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_active_user),
    x_company_id: int = Header(...),
):
    """Return paginated recent API call logs for the company."""
    from app.models.api_key_log import ApiKeyLog

    company_id = x_company_id
    since = datetime.utcnow() - timedelta(days=days)

    q = db.query(ApiKeyLog).filter(
        ApiKeyLog.company_id == company_id,
        ApiKeyLog.created_at >= since,
    )
    if api_key_id:
        q = q.filter(ApiKeyLog.api_key_id == api_key_id)

    total = q.count()
    logs = (
        q.order_by(ApiKeyLog.created_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )

    # Enrich with key names
    key_ids = list({log.api_key_id for log in logs})
    keys_map = {}
    if key_ids:
        key_objs = db.query(ApiKey).filter(ApiKey.id.in_(key_ids)).all()
        keys_map = {k.id: k.name for k in key_objs}

    return {
        "total": total,
        "page": page,
        "limit": limit,
        "pages": (total + limit - 1) // limit,
        "logs": [
            {
                "id": log.id,
                "api_key_id": log.api_key_id,
                "api_key_name": keys_map.get(log.api_key_id, "Unknown"),
                "endpoint": log.endpoint,
                "method": log.method,
                "status_code": log.status_code,
                "response_ms": log.response_ms,
                "created_at": log.created_at.isoformat(),
            }
            for log in logs
        ],
    }
