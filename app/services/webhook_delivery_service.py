"""
Webhook Delivery Service

Handles firing webhooks to external URLs and logging the delivery results
to WebhookDeliveryLog for audit/debugging purposes.
"""
import json
import logging
from typing import Any, Dict

import httpx
from sqlalchemy.orm import Session

from app.models.webhook import Webhook
from app.models.webhook_delivery_log import WebhookDeliveryLog

logger = logging.getLogger(__name__)


async def fire_webhook(
    db: Session,
    company_id: int,
    event_type: str,
    payload_dict: Dict[str, Any],
    webhook_url: str,
    attempt: int = 1,
) -> bool:
    """
    POST `payload_dict` as JSON to `webhook_url` with a 10-second timeout.
    Logs the result (success or failure) to WebhookDeliveryLog.
    Always returns without raising — exceptions are caught and logged.

    Returns:
        True if the delivery succeeded (2xx response), False otherwise.
    """
    payload_json = json.dumps(payload_dict)
    status_code: int | None = None
    success = False
    error_message: str | None = None

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                webhook_url,
                content=payload_json,
                headers={"Content-Type": "application/json"},
            )
            status_code = response.status_code
            success = 200 <= status_code < 300
            if not success:
                error_message = f"HTTP {status_code}: {response.text[:400]}"
    except httpx.TimeoutException as exc:
        error_message = f"Request timed out: {exc}"
        logger.warning("[WebhookDelivery] Timeout firing %s to %s: %s", event_type, webhook_url, exc)
    except httpx.RequestError as exc:
        error_message = f"Request error: {exc}"
        logger.warning("[WebhookDelivery] Request error firing %s to %s: %s", event_type, webhook_url, exc)
    except Exception as exc:
        error_message = f"Unexpected error: {exc}"
        logger.exception("[WebhookDelivery] Unexpected error firing %s to %s", event_type, webhook_url)

    # Always write the delivery log — even on failure
    try:
        log_entry = WebhookDeliveryLog(
            company_id=company_id,
            event_type=event_type,
            payload=payload_json,
            webhook_url=webhook_url,
            status_code=status_code,
            success=success,
            error_message=error_message,
            attempt=attempt,
        )
        db.add(log_entry)
        db.commit()
    except Exception as log_exc:
        logger.exception("[WebhookDelivery] Failed to write delivery log: %s", log_exc)
        try:
            db.rollback()
        except Exception:
            pass

    return success


async def fire_company_webhooks(
    db: Session,
    company_id: int,
    event_type: str,
    payload_dict: Dict[str, Any],
) -> None:
    """
    Query all active Webhooks for `company_id` whose trigger_event matches
    `event_type` (exact match) or is the wildcard `"*"`, then fire each one.

    Errors per-webhook are caught individually so one bad webhook cannot
    prevent the others from being called.
    """
    try:
        webhooks = (
            db.query(Webhook)
            .filter(
                Webhook.company_id == company_id,
                Webhook.is_active == True,
                Webhook.trigger_event.in_([event_type, "*"]),
            )
            .all()
        )
    except Exception as exc:
        logger.exception("[WebhookDelivery] Failed to query webhooks for company %s: %s", company_id, exc)
        return

    for webhook in webhooks:
        try:
            await fire_webhook(
                db=db,
                company_id=company_id,
                event_type=event_type,
                payload_dict=payload_dict,
                webhook_url=webhook.url,
            )
        except Exception as exc:
            # Extremely defensive — fire_webhook already catches, but just in case
            logger.exception(
                "[WebhookDelivery] Unhandled error for webhook %s (company %s): %s",
                webhook.id,
                company_id,
                exc,
            )
