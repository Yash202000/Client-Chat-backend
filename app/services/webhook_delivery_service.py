"""
Webhook Delivery Service

Handles firing webhooks to external URLs and logging the delivery results
to WebhookDeliveryLog for audit/debugging purposes.

Retry schedule (exponential back-off):
  Attempt 1 — immediate (on first call)
  Attempt 2 — 5 minutes after failure
  Attempt 3 — 30 minutes after failure
  After attempt 3 — no more retries (next_retry_at set to None)
"""
import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict

import httpx
from sqlalchemy.orm import Session

from app.models.webhook import Webhook
from app.models.webhook_delivery_log import WebhookDeliveryLog

logger = logging.getLogger(__name__)

# Delay (seconds) before each retry attempt.
# Index 0 = first attempt (immediate), index 1 = after 1st failure, index 2 = after 2nd failure.
_RETRY_DELAYS_SECONDS = [0, 5 * 60, 30 * 60]
_MAX_ATTEMPTS = len(_RETRY_DELAYS_SECONDS)


async def fire_webhook(
    db: Session,
    company_id: int,
    event_type: str,
    payload_dict: Dict[str, Any],
    webhook_url: str,
    attempt: int = 1,
    webhook_id: int | None = None,
) -> bool:
    """
    POST `payload_dict` as JSON to `webhook_url` with a 10-second timeout.
    Logs the result (success or failure) to WebhookDeliveryLog.
    On failure, schedules a retry by setting next_retry_at if attempts remain.
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

    # Determine retry scheduling for failed deliveries
    next_retry_at: datetime | None = None
    if not success and attempt < _MAX_ATTEMPTS:
        delay = _RETRY_DELAYS_SECONDS[attempt]  # index = next attempt index (0-based delay list)
        next_retry_at = datetime.utcnow() + timedelta(seconds=delay)
        logger.info(
            "[WebhookDelivery] Scheduling retry attempt %d for %s in %ds (at %s)",
            attempt + 1,
            webhook_url,
            delay,
            next_retry_at.isoformat(),
        )
    elif not success:
        logger.warning(
            "[WebhookDelivery] Exhausted all %d attempts for %s — giving up.",
            _MAX_ATTEMPTS,
            webhook_url,
        )

    # Always write the delivery log — even on failure
    try:
        log_entry = WebhookDeliveryLog(
            company_id=company_id,
            webhook_id=webhook_id,
            event_type=event_type,
            payload=payload_json,
            webhook_url=webhook_url,
            status_code=status_code,
            success=success,
            error_message=error_message,
            attempt=attempt,
            next_retry_at=next_retry_at,
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


async def retry_failed_webhooks(db: Session) -> None:
    """
    Called by the APScheduler job every 5 minutes.
    Finds all failed WebhookDeliveryLog rows whose next_retry_at has passed
    and retries them (up to _MAX_ATTEMPTS total).

    Each retry creates a NEW log row so the audit trail is fully preserved.
    The original (or previous) failed row has its next_retry_at cleared to
    prevent duplicate retries.
    """
    now = datetime.utcnow()

    try:
        pending = (
            db.query(WebhookDeliveryLog)
            .filter(
                WebhookDeliveryLog.success == False,
                WebhookDeliveryLog.next_retry_at.isnot(None),
                WebhookDeliveryLog.next_retry_at <= now,
                WebhookDeliveryLog.attempt < _MAX_ATTEMPTS,
            )
            .limit(100)
            .all()
        )
    except Exception as exc:
        logger.exception("[WebhookDelivery] Failed to query pending retries: %s", exc)
        return

    if not pending:
        return

    logger.info("[WebhookDelivery] Processing %d webhook retry entries.", len(pending))

    for log in pending:
        try:
            # Clear next_retry_at on the parent log to prevent re-processing
            log.next_retry_at = None
            db.commit()

            # Parse stored payload
            try:
                payload_dict = json.loads(log.payload or "{}")
            except (json.JSONDecodeError, TypeError):
                payload_dict = {}

            next_attempt = log.attempt + 1
            await fire_webhook(
                db=db,
                company_id=log.company_id,
                event_type=log.event_type or "webhook",
                payload_dict=payload_dict,
                webhook_url=log.webhook_url,
                attempt=next_attempt,
                webhook_id=log.webhook_id,
            )
        except Exception as exc:
            logger.error(
                "[WebhookDelivery] Unexpected error retrying webhook log id=%s: %s",
                log.id,
                exc,
            )


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
                webhook_id=webhook.id,
            )
        except Exception as exc:
            # Extremely defensive — fire_webhook already catches, but just in case
            logger.exception(
                "[WebhookDelivery] Unhandled error for webhook %s (company %s): %s",
                webhook.id,
                company_id,
                exc,
            )
