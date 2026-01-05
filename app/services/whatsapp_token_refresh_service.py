"""
WhatsApp Token Refresh Background Service.

Proactively refreshes WhatsApp OAuth tokens before they expire.
Runs as a scheduled background job.
"""
import logging
from datetime import datetime
from typing import Dict
from sqlalchemy.orm import Session

from app.models import integration as models_integration
from app.services import integration_service
from app.services.whatsapp_token_service import (
    whatsapp_token_service,
    PROACTIVE_REFRESH_THRESHOLD_DAYS
)
from app.core.database import SessionLocal

logger = logging.getLogger(__name__)


async def refresh_expiring_whatsapp_tokens(db: Session) -> Dict[str, int]:
    """
    Background job to proactively refresh WhatsApp tokens that are nearing expiry.

    This runs periodically (e.g., every hour) to ensure tokens are refreshed
    well before they expire.

    Args:
        db: Database session

    Returns:
        Dict with refresh statistics: checked, refreshed, failed, skipped
    """
    stats = {
        "checked": 0,
        "refreshed": 0,
        "failed": 0,
        "skipped": 0
    }

    try:
        # Get all enabled WhatsApp integrations
        all_whatsapp_integrations = db.query(
            models_integration.Integration
        ).filter(
            models_integration.Integration.type == "whatsapp",
            models_integration.Integration.enabled == True
        ).all()

        logger.info(f"[WhatsApp Token Refresh] Checking {len(all_whatsapp_integrations)} WhatsApp integrations")

        for integration in all_whatsapp_integrations:
            stats["checked"] += 1

            try:
                credentials = whatsapp_token_service.get_credentials_with_expiry_check(integration)

                # Skip non-OAuth integrations
                if not credentials.get("is_oauth_enabled"):
                    stats["skipped"] += 1
                    logger.debug(f"Integration {integration.id}: OAuth not enabled, skipping")
                    continue

                # Check if token needs proactive refresh
                if whatsapp_token_service.is_token_expiring_soon(
                    credentials,
                    threshold_days=PROACTIVE_REFRESH_THRESHOLD_DAYS
                ):
                    token_expires_at = credentials.get("token_expires_at")
                    current_time = datetime.utcnow().timestamp()
                    hours_until_expiry = (token_expires_at - current_time) / 3600

                    logger.info(
                        f"Integration {integration.id}: Token expires in {hours_until_expiry:.1f} hours, refreshing"
                    )

                    # Force refresh by calling ensure_valid_token
                    # We temporarily modify needs_refresh to force refresh
                    await whatsapp_token_service.ensure_valid_token(db, integration)

                    # Check if refresh was successful by re-reading credentials
                    updated_credentials = integration_service.get_decrypted_credentials(integration)
                    if updated_credentials.get("refresh_error"):
                        stats["failed"] += 1
                        logger.error(
                            f"Integration {integration.id}: Refresh failed - {updated_credentials.get('refresh_error')}"
                        )
                    else:
                        stats["refreshed"] += 1
                        logger.info(f"Integration {integration.id}: Token refreshed successfully")
                else:
                    stats["skipped"] += 1
                    logger.debug(f"Integration {integration.id}: Token not expiring soon, skipping")

            except Exception as e:
                logger.error(f"Error processing integration {integration.id}: {e}")
                stats["failed"] += 1

        logger.info(
            f"[WhatsApp Token Refresh] Completed: "
            f"checked={stats['checked']}, refreshed={stats['refreshed']}, "
            f"failed={stats['failed']}, skipped={stats['skipped']}"
        )

    except Exception as e:
        logger.error(f"[WhatsApp Token Refresh] Job failed: {e}")
        raise

    return stats


async def run_whatsapp_token_refresh_scheduler():
    """
    Wrapper to run the token refresh with a fresh DB session.
    Called by APScheduler.
    """
    logger.info("[WhatsApp Token Refresh] Starting scheduled token refresh")
    db = SessionLocal()
    try:
        await refresh_expiring_whatsapp_tokens(db)
    finally:
        db.close()


def get_token_status_for_integration(db: Session, integration_id: int, company_id: int) -> Dict:
    """
    Get detailed token status for a specific WhatsApp integration.

    Args:
        db: Database session
        integration_id: Integration ID
        company_id: Company ID

    Returns:
        Dict with token status information
    """
    integration = integration_service.get_integration(db, integration_id, company_id)

    if not integration or integration.type != "whatsapp":
        return {"error": "WhatsApp integration not found"}

    credentials = whatsapp_token_service.get_credentials_with_expiry_check(integration)

    result = {
        "integration_id": integration.id,
        "integration_name": integration.name,
        "is_oauth_enabled": credentials.get("is_oauth_enabled", False),
        "token_type": credentials.get("token_type", "legacy"),
        "needs_refresh": credentials.get("needs_refresh", False),
        "refresh_error": credentials.get("refresh_error"),
    }

    # Add expiry information if available
    if credentials.get("token_expires_at"):
        expires_at = credentials["token_expires_at"]
        current_time = datetime.utcnow().timestamp()
        result["token_expires_at"] = datetime.fromtimestamp(expires_at).isoformat()
        result["hours_until_expiry"] = round((expires_at - current_time) / 3600, 1)

    if credentials.get("last_refresh_at"):
        result["last_refresh_at"] = datetime.fromtimestamp(
            credentials["last_refresh_at"]
        ).isoformat()

    return result
