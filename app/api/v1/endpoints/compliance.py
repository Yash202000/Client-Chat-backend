"""
Compliance & Trust Endpoints

Designed to integrate with Vanta, Drata, and similar compliance automation tools.
All endpoints require a valid API key passed as Bearer token.

GET  /compliance/sub-processors       — public list of sub-processors
GET  /compliance/security-events      — recent access/security events (Vanta/Drata polling)
GET  /compliance/users-access         — current user list with roles (for access review)
GET  /compliance/health               — public uptime/health signal for status page
"""
from datetime import datetime, timedelta
from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, get_current_active_user
from app.models.user import User
from app.models.audit_log import AuditLog

router = APIRouter()


# ---------------------------------------------------------------------------
# Sub-processors — public, no auth required
# ---------------------------------------------------------------------------

SUB_PROCESSORS = [
    {
        "name": "Amazon Web Services (AWS)",
        "purpose": "Infrastructure hosting, object storage (S3), and compute",
        "location": "US, EU (configurable)",
        "data_types": ["All platform data"],
        "dpa_url": "https://aws.amazon.com/agreement/",
    },
    {
        "name": "OpenAI",
        "purpose": "Large language model inference (GPT-4o, Whisper STT)",
        "location": "US",
        "data_types": ["Message content", "Voice transcripts"],
        "dpa_url": "https://openai.com/policies/data-processing-addendum",
    },
    {
        "name": "Groq",
        "purpose": "High-speed LLM inference (Llama, Mixtral)",
        "location": "US",
        "data_types": ["Message content"],
        "dpa_url": "https://groq.com/privacy-policy/",
    },
    {
        "name": "Google (Gemini / Vertex AI)",
        "purpose": "LLM inference and OAuth authentication",
        "location": "US, EU",
        "data_types": ["Message content", "User email (OAuth)"],
        "dpa_url": "https://cloud.google.com/terms/data-processing-addendum",
    },
    {
        "name": "Twilio",
        "purpose": "Voice calls, SMS, and WhatsApp messaging",
        "location": "US, EU",
        "data_types": ["Phone numbers", "Call recordings", "SMS content"],
        "dpa_url": "https://www.twilio.com/en-us/legal/data-protection-addendum",
    },
    {
        "name": "LiveKit",
        "purpose": "Real-time video and audio conferencing",
        "location": "US",
        "data_types": ["Video/audio streams"],
        "dpa_url": "https://livekit.io/privacy",
    },
    {
        "name": "Meta (Facebook / Instagram / WhatsApp)",
        "purpose": "Messenger, Instagram DM, and WhatsApp Business API channels",
        "location": "US, EU",
        "data_types": ["Message content", "User identifiers"],
        "dpa_url": "https://www.facebook.com/legal/terms/dataprocessing",
    },
    {
        "name": "PostgreSQL (self-hosted)",
        "purpose": "Primary relational database",
        "location": "Customer-controlled",
        "data_types": ["All platform data"],
        "dpa_url": None,
    },
    {
        "name": "Redis (self-hosted)",
        "purpose": "Session cache, WebSocket presence, rate limiting",
        "location": "Customer-controlled",
        "data_types": ["Session tokens", "Presence data"],
        "dpa_url": None,
    },
    {
        "name": "LinkedIn",
        "purpose": "OAuth login and lead enrichment API",
        "location": "US",
        "data_types": ["User profile (OAuth)", "Lead data"],
        "dpa_url": "https://www.linkedin.com/legal/l/dpa",
    },
]


@router.get("/sub-processors")
async def list_sub_processors():
    """Public — returns the current list of sub-processors."""
    return {
        "last_updated": "2026-05-03",
        "count": len(SUB_PROCESSORS),
        "sub_processors": SUB_PROCESSORS,
    }


@router.get("/health")
async def health():
    """Public — lightweight health check for status pages."""
    return {"status": "operational", "timestamp": datetime.utcnow().isoformat() + "Z"}


# ---------------------------------------------------------------------------
# Authenticated endpoints (Vanta / Drata use these via service account token)
# ---------------------------------------------------------------------------


class SecurityEventItem(BaseModel):
    id: int
    occurred_at: str
    event_type: str
    actor_email: Optional[str] = None
    actor_id: Optional[int] = None
    resource_type: Optional[str] = None
    resource_id: Optional[int] = None
    resource_name: Optional[str] = None
    ip_address: Optional[str] = None
    details: Optional[dict] = None


class UserAccessItem(BaseModel):
    id: int
    email: str
    full_name: Optional[str] = None
    role: Optional[str] = None
    is_admin: bool
    is_active: bool
    last_login_at: Optional[str] = None
    created_at: Optional[str] = None


# Security events that are relevant for Vanta/Drata evidence collection
SECURITY_EVENT_ACTIONS = {
    "user.created", "user.deleted", "user.role_changed", "user.deactivated",
    "user.activated", "auth.login", "auth.login_failed", "auth.logout",
    "gdpr.user_erased", "gdpr.company_erased",
    "api_key.created", "api_key.deleted",
    "credential.created", "credential.deleted",
    "role.created", "role.updated", "role.deleted",
    "permission.granted", "permission.revoked",
    "saml.sso_enabled", "saml.sso_disabled",
    "scim.token_regenerated",
    "data_export.initiated",
}


@router.get("/security-events", response_model=List[SecurityEventItem])
async def get_security_events(
    since: Optional[datetime] = Query(
        None,
        description="Return events after this timestamp (ISO-8601). Defaults to last 30 days.",
    ),
    limit: int = Query(500, ge=1, le=2000),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """
    Returns access and security events for the company — intended for Vanta / Drata polling.

    Filters audit log entries to the subset relevant for compliance evidence:
    user provisioning, authentication events, key management, role/permission changes.
    """
    if not current_user.is_admin and not current_user.is_super_admin:
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Admin access required")

    cutoff = since or (datetime.utcnow() - timedelta(days=30))

    logs = (
        db.query(AuditLog)
        .filter(
            AuditLog.company_id == current_user.company_id,
            AuditLog.created_at >= cutoff,
            AuditLog.action.in_(SECURITY_EVENT_ACTIONS),
        )
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
        .all()
    )

    result = []
    for log in logs:
        actor_email = None
        if log.user:
            actor_email = log.user.email

        result.append(
            SecurityEventItem(
                id=log.id,
                occurred_at=log.created_at.isoformat() + "Z",
                event_type=log.action,
                actor_email=actor_email,
                actor_id=log.user_id,
                resource_type=log.entity_type,
                resource_id=log.entity_id,
                resource_name=log.entity_name,
                ip_address=log.ip_address,
                details=log.changes,
            )
        )

    return result


@router.get("/users-access", response_model=List[UserAccessItem])
async def get_users_access(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """
    Returns the current user roster with roles — used by Vanta/Drata for
    periodic access reviews.
    """
    if not current_user.is_admin and not current_user.is_super_admin:
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Admin access required")

    users = (
        db.query(User)
        .filter(User.company_id == current_user.company_id)
        .all()
    )

    result = []
    for u in users:
        first = u.first_name or ""
        last = u.last_name or ""
        full_name = (first + " " + last).strip() or None
        role_name = u.role.name if u.role else None

        result.append(
            UserAccessItem(
                id=u.id,
                email=u.email,
                full_name=full_name,
                role=role_name,
                is_admin=u.is_admin or False,
                is_active=u.is_active,
                last_login_at=u.last_login_at.isoformat() + "Z" if u.last_login_at else None,
                created_at=None,
            )
        )

    return result
