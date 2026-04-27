"""
Queue Overflow / SLA background service.

Runs every 30 seconds via APScheduler.
1. Finds waiting entries older than SLA threshold (default 120s).
2. For Twilio entries: redirects call to voicemail TwiML and marks status='voicemail'.
3. After additional overflow threshold (default 60s more): bumps priority +1 and broadcasts alert.
"""
import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.call_queue import CallQueueEntry
from app.models.integration import Integration
from app.services import integration_service

logger = logging.getLogger(__name__)

# These match defaults in /voice/queue/sla-config
DEFAULT_SLA_SECONDS = 120
DEFAULT_ESCALATE_AFTER_SECONDS = 60


def _get_sla_config(company_id: int) -> dict:
    """Fetch SLA config from in-memory store (same as endpoint module)."""
    try:
        from app.api.v1.endpoints.call_queue import _sla_configs, _DEFAULT_SLA
        return _sla_configs.get(company_id, _DEFAULT_SLA.copy())
    except Exception:
        return {
            "sla_seconds": DEFAULT_SLA_SECONDS,
            "overflow_action": "voicemail",
            "escalate_after_seconds": DEFAULT_ESCALATE_AFTER_SECONDS,
        }


def _get_twilio_client(db: Session, company_id: int):
    """Return a Twilio client for the company, or None if not configured."""
    try:
        from twilio.rest import Client as TwilioClient
        integration = db.query(Integration).filter(
            Integration.company_id == company_id,
            Integration.type == "twilio_voice",
            Integration.is_active == True,
        ).first()
        if not integration:
            return None, None
        creds = integration_service.get_decrypted_credentials(integration)
        client = TwilioClient(creds["account_sid"], creds["auth_token"])
        return client, creds
    except Exception as e:
        logger.warning(f"[QueueOverflow] Could not build Twilio client for company {company_id}: {e}")
        return None, None


async def run_queue_overflow_check():
    """Main scheduled task: check SLA breaches and overflow entries."""
    db: Session = SessionLocal()
    try:
        now = datetime.utcnow()

        # Get all companies with waiting entries
        company_ids = (
            db.query(CallQueueEntry.company_id)
            .filter(CallQueueEntry.status == "waiting")
            .distinct()
            .all()
        )

        for (company_id,) in company_ids:
            cfg = _get_sla_config(company_id)
            sla_secs = cfg.get("sla_seconds", DEFAULT_SLA_SECONDS)
            overflow_action = cfg.get("overflow_action", "voicemail")
            escalate_after = cfg.get("escalate_after_seconds", DEFAULT_ESCALATE_AFTER_SECONDS)

            sla_cutoff = now - timedelta(seconds=sla_secs)

            # Entries that have breached SLA and are still waiting (not yet sent to voicemail)
            breached = (
                db.query(CallQueueEntry)
                .filter(
                    CallQueueEntry.company_id == company_id,
                    CallQueueEntry.status == "waiting",
                    CallQueueEntry.entered_at <= sla_cutoff,
                    CallQueueEntry.overflow_at == None,
                )
                .all()
            )

            for entry in breached:
                logger.info(
                    f"[QueueOverflow] SLA breached for entry {entry.id} (call {entry.call_sid}) "
                    f"company {company_id}, action={overflow_action}"
                )

                if overflow_action == "voicemail" and entry.source == "twilio":
                    _redirect_to_voicemail(db, entry, company_id)
                elif overflow_action == "drop":
                    entry.status = "abandoned"
                    entry.ended_at = now
                    entry.overflow_at = now
                    db.commit()
                else:
                    # escalate: mark overflow time and bump priority below
                    entry.overflow_at = now
                    db.commit()

            # Entries already overflowed — escalate priority after escalate_after_seconds
            escalate_cutoff = now - timedelta(seconds=sla_secs + escalate_after)
            to_escalate = (
                db.query(CallQueueEntry)
                .filter(
                    CallQueueEntry.company_id == company_id,
                    CallQueueEntry.status == "waiting",
                    CallQueueEntry.entered_at <= escalate_cutoff,
                    CallQueueEntry.overflow_at != None,
                    CallQueueEntry.priority < 2,
                )
                .all()
            )

            for entry in to_escalate:
                entry.priority = min(entry.priority + 1, 2)
                db.commit()
                logger.info(f"[QueueOverflow] Escalated priority for entry {entry.id} to {entry.priority}")

                # Broadcast alert
                try:
                    import json
                    from app.services.connection_manager import manager
                    alert = json.dumps({
                        "type": "queue_sla_escalation",
                        "entry_id": entry.id,
                        "call_sid": entry.call_sid,
                        "caller_number": entry.caller_number,
                        "priority": entry.priority,
                        "wait_secs": int((now - entry.entered_at).total_seconds()),
                    })
                    import asyncio
                    asyncio.create_task(manager.broadcast_to_company(company_id, alert))
                except Exception as be:
                    logger.warning(f"[QueueOverflow] Broadcast failed: {be}")

        # Handle voicemail entries that got a recording — they're done, nothing more to do
    except Exception as e:
        logger.error(f"[QueueOverflow] Error in overflow check: {e}", exc_info=True)
    finally:
        db.close()


def _redirect_to_voicemail(db: Session, entry: CallQueueEntry, company_id: int):
    """Redirect a live Twilio call to the voicemail TwiML endpoint."""
    try:
        twilio_client, creds = _get_twilio_client(db, company_id)
        if twilio_client:
            # Determine public host from settings
            from app.core.config import settings
            public_host = getattr(settings, 'PUBLIC_HOST', 'localhost')
            voicemail_url = f"https://{public_host}/api/v1/voice/queue/twiml/voicemail"
            twilio_client.calls(entry.call_sid).update(url=voicemail_url, method="POST")
            logger.info(f"[QueueOverflow] Redirected {entry.call_sid} to voicemail")
    except Exception as e:
        logger.warning(f"[QueueOverflow] Could not redirect to voicemail: {e}")

    entry.status = "voicemail"
    entry.overflow_at = datetime.utcnow()
    db.commit()
