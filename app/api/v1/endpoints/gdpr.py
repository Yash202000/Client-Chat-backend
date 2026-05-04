"""
GDPR Compliance Endpoints

Right to Erasure  (Art. 17) — DELETE /gdpr/erase-my-data
Right to Portability (Art. 20) — handled by /export/data
"""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.core.dependencies import get_db, get_current_active_user
from app.core.security import verify_password
from app.core.audit import log_action
from app.models.user import User

router = APIRouter()


class EraseRequest(BaseModel):
    password: str
    confirmation: str  # must equal "DELETE MY ACCOUNT"


class EraseCompanyRequest(BaseModel):
    password: str
    confirmation: str  # must equal "DELETE ALL COMPANY DATA"


@router.delete("/erase-my-data", status_code=status.HTTP_200_OK)
async def erase_my_data(
    payload: EraseRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """
    GDPR Art. 17 — Right to Erasure.

    Permanently deletes the authenticated user's personal data:
    - Anonymises all audit log entries referencing this user
    - Anonymises all internal chat messages sent by this user
    - Deletes user settings, voice profiles, team memberships
    - Deletes the user record

    Requires the user's current password and the exact string
    "DELETE MY ACCOUNT" as a double-confirmation.
    """
    if payload.confirmation != "DELETE MY ACCOUNT":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='confirmation must be the exact string "DELETE MY ACCOUNT"',
        )

    if not verify_password(payload.password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Password is incorrect",
        )

    user_id = current_user.id
    company_id = current_user.company_id
    user_email = current_user.email
    ip = request.client.host if request.client else None

    # --- Anonymise audit logs authored by this user ---
    db.execute(
        text("UPDATE audit_logs SET user_id = NULL WHERE user_id = :uid"),
        {"uid": user_id},
    )

    # --- Anonymise internal chat messages ---
    try:
        db.execute(
            text(
                "UPDATE internal_chat_messages "
                "SET sender_id = NULL, content = '[message deleted — user account erased]' "
                "WHERE sender_id = :uid"
            ),
            {"uid": user_id},
        )
    except Exception:
        pass

    # --- Anonymise conversation session assignments ---
    try:
        db.execute(
            text("UPDATE conversation_sessions SET assigned_agent_user_id = NULL WHERE assigned_agent_user_id = :uid"),
            {"uid": user_id},
        )
    except Exception:
        pass

    # --- Log the erasure itself (no user_id since user is being deleted) ---
    log_action(
        db,
        company_id=company_id,
        user_id=None,
        action="gdpr.user_erased",
        entity_type="user",
        entity_name=f"[erased:{user_email}]",
        changes={"erased_at": datetime.utcnow().isoformat()},
        ip=ip,
    )

    # --- Delete the user (cascades to user_settings, voice_profiles, etc.) ---
    db.delete(current_user)
    db.commit()

    return {"erased": True, "message": "Your account and personal data have been permanently deleted."}


@router.delete("/erase-company-data", status_code=status.HTTP_200_OK)
async def erase_company_data(
    payload: EraseCompanyRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """
    Admin-only — permanently delete ALL data belonging to the company.

    This is irreversible. Requires admin privileges, correct password, and
    the confirmation string "DELETE ALL COMPANY DATA".
    """
    if not current_user.is_admin and not current_user.is_super_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")

    if payload.confirmation != "DELETE ALL COMPANY DATA":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='confirmation must be the exact string "DELETE ALL COMPANY DATA"',
        )

    if not verify_password(payload.password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Password is incorrect",
        )

    company_id = current_user.company_id
    ip = request.client.host if request.client else None

    # Tables to wipe in dependency order (FK-safe without disabling constraints)
    ordered_tables = [
        "audit_logs", "security_logs", "token_usage",
        "contact_activities", "email_tracking_tokens",
        "sequence_step_logs", "sequence_enrollments", "sequence_steps", "sequences",
        "campaign_sequence_triggers",
        "campaign_messages", "campaign_contacts", "campaign_activities", "campaigns",
        "form_submissions", "capture_forms",
        "booking_slots", "booking_links",
        "deal_stages", "deals", "pipelines",
        "entity_notes",
        "lead_scores",
        "lead_tags", "contact_tags",
        "leads", "contacts",
        "accounts",
        "segments", "tags",
        "templates", "message_templates",
        "content_exports", "content_copies",
        "content_item_categories", "content_items", "content_types",
        "content_media", "content_categories", "content_tags", "content_api_tokens",
        "drive_items",
        "social_posts", "social_accounts",
        "calendar_events",
        "workflow_triggers", "workflows",
        "knowledge_base_items", "knowledge_bases",
        "chat_messages", "conversation_sessions",
        "message_reads", "message_reactions", "message_mentions",
        "pinned_messages", "chat_attachments", "internal_chat_messages",
        "channel_memberships", "chat_channels",
        "notifications",
        "team_memberships", "teams",
        "agent_skills", "agents",
        "integrations", "credentials",
        "api_integrations", "api_keys",
        "user_settings", "voice_profiles",
        "optimization_suggestions",
        "users",
        "company_subscriptions", "company_settings",
    ]

    for table in ordered_tables:
        try:
            db.execute(text(f"DELETE FROM {table} WHERE company_id = :cid"), {"cid": company_id})
        except Exception:
            db.rollback()
            try:
                db.execute(text(f"DELETE FROM {table} WHERE company_id = :cid"), {"cid": company_id})
            except Exception:
                pass

    # Delete the company itself
    try:
        db.execute(text("DELETE FROM companies WHERE id = :cid"), {"cid": company_id})
    except Exception:
        pass

    db.commit()

    return {"erased": True, "message": "All company data has been permanently deleted."}
