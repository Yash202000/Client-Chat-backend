"""
Broadcast Service — one-time WhatsApp/SMS blast to a segment or all contacts.

Flow:
  1. Create broadcast (draft)
  2. Call send_broadcast() — runs async, updates progress in DB
  3. Poll GET /broadcasts/{id} for live status
"""
import asyncio
import logging
from datetime import datetime
from typing import Optional, List

from sqlalchemy.orm import Session

from app.models.broadcast import Broadcast, BroadcastContact, BroadcastChannel, BroadcastStatus, BroadcastContactStatus
from app.models.contact import Contact, OptInStatus
from app.models.segment import Segment

logger = logging.getLogger(__name__)

BATCH_SIZE = 10        # contacts per batch
BATCH_DELAY = 1.0      # seconds between batches (rate limiting)


def _get_contacts(db: Session, broadcast: Broadcast) -> List[Contact]:
    """Resolve which contacts to message, excluding opted-out contacts."""
    from app.models.broadcast import BroadcastChannel
    is_email = broadcast.channel == BroadcastChannel.EMAIL

    if broadcast.segment_id:
        from app.services.campaign_execution_service import get_contacts_from_segment
        contacts = get_contacts_from_segment(db, broadcast.segment_id, broadcast.company_id)
        contacts = [c for c in contacts if c.opt_in_status != OptInStatus.OPTED_OUT]
        if is_email:
            return [c for c in contacts if c.email and c.email.strip()]
        return contacts

    if is_email:
        return (
            db.query(Contact)
            .filter(
                Contact.company_id == broadcast.company_id,
                Contact.email != None,
                Contact.email != "",
                Contact.opt_in_status != OptInStatus.OPTED_OUT,
            )
            .all()
        )

    # Phone-based channels — target all contacts with phone numbers
    return (
        db.query(Contact)
        .filter(
            Contact.company_id == broadcast.company_id,
            Contact.phone_number != None,
            Contact.phone_number != "",
            Contact.opt_in_status != OptInStatus.OPTED_OUT,
        )
        .all()
    )


def create_broadcast(
    db: Session,
    company_id: int,
    name: str,
    channel: str,
    message: str,
    subject: Optional[str] = None,
    segment_id: Optional[int] = None,
    scheduled_at: Optional[datetime] = None,
    created_by_user_id: Optional[int] = None,
) -> Broadcast:
    broadcast = Broadcast(
        company_id=company_id,
        name=name,
        channel=BroadcastChannel(channel),
        subject=subject,
        message=message,
        segment_id=segment_id,
        scheduled_at=scheduled_at,
        status=BroadcastStatus.SCHEDULED if scheduled_at else BroadcastStatus.DRAFT,
        created_by_user_id=created_by_user_id,
    )
    db.add(broadcast)
    db.commit()
    db.refresh(broadcast)
    return broadcast


def get_broadcast(db: Session, broadcast_id: int, company_id: int) -> Optional[Broadcast]:
    return db.query(Broadcast).filter(
        Broadcast.id == broadcast_id, Broadcast.company_id == company_id
    ).first()


def list_broadcasts(db: Session, company_id: int, limit: int = 50, offset: int = 0) -> List[Broadcast]:
    return (
        db.query(Broadcast)
        .filter(Broadcast.company_id == company_id)
        .order_by(Broadcast.created_at.desc())
        .offset(offset).limit(limit).all()
    )


def delete_broadcast(db: Session, broadcast_id: int, company_id: int) -> bool:
    broadcast = get_broadcast(db, broadcast_id, company_id)
    if not broadcast or broadcast.status == BroadcastStatus.RUNNING:
        return False
    db.delete(broadcast)
    db.commit()
    return True


def get_broadcast_contacts(
    db: Session, broadcast_id: int, company_id: int, limit: int = 100, offset: int = 0
) -> List[BroadcastContact]:
    return (
        db.query(BroadcastContact)
        .filter(BroadcastContact.broadcast_id == broadcast_id, BroadcastContact.company_id == company_id)
        .offset(offset).limit(limit).all()
    )


async def send_broadcast(db: Session, broadcast_id: int, company_id: int) -> None:
    """
    Async fire-and-forget broadcast runner.
    Sends messages in batches with rate limiting.
    """
    broadcast = get_broadcast(db, broadcast_id, company_id)
    if not broadcast:
        logger.error(f"[Broadcast] {broadcast_id} not found")
        return
    if broadcast.status == BroadcastStatus.RUNNING:
        logger.warning(f"[Broadcast] {broadcast_id} already running")
        return

    # Resolve contacts
    contacts = _get_contacts(db, broadcast)

    # Bootstrap broadcast contact rows
    db.query(BroadcastContact).filter(BroadcastContact.broadcast_id == broadcast_id).delete()
    is_email_channel = broadcast.channel == BroadcastChannel.EMAIL
    for contact in contacts:
        has_address = (contact.email and contact.email.strip()) if is_email_channel else bool(contact.phone_number)
        status = BroadcastContactStatus.PENDING if has_address else BroadcastContactStatus.SKIPPED
        db.add(BroadcastContact(
            broadcast_id=broadcast_id,
            contact_id=contact.id,
            company_id=company_id,
            status=status,
        ))

    broadcast.total_contacts = len(contacts)
    broadcast.status = BroadcastStatus.RUNNING
    broadcast.started_at = datetime.utcnow()
    db.commit()

    logger.info(f"[Broadcast] Starting '{broadcast.name}' — {len(contacts)} contacts via {broadcast.channel.value}")

    sent = failed = skipped = 0

    for i in range(0, len(contacts), BATCH_SIZE):
        batch = contacts[i: i + BATCH_SIZE]
        for contact in batch:
            bc = db.query(BroadcastContact).filter(
                BroadcastContact.broadcast_id == broadcast_id,
                BroadcastContact.contact_id == contact.id,
            ).first()

            has_address = (contact.email and contact.email.strip()) if is_email_channel else bool(contact.phone_number)
            if not has_address:
                if bc:
                    bc.status = BroadcastContactStatus.SKIPPED
                skipped += 1
                continue

            try:
                if broadcast.channel == BroadcastChannel.WHATSAPP:
                    await _send_whatsapp(db, company_id, contact, broadcast.message)
                elif broadcast.channel == BroadcastChannel.EMAIL:
                    await _send_email_broadcast(db, company_id, contact, broadcast.subject, broadcast.message)
                else:
                    _send_sms(db, company_id, contact, broadcast.message)

                if bc:
                    bc.status = BroadcastContactStatus.SENT
                    bc.sent_at = datetime.utcnow()
                sent += 1
            except Exception as e:
                if bc:
                    bc.status = BroadcastContactStatus.FAILED
                    bc.error_message = str(e)[:500]
                failed += 1
                logger.warning(f"[Broadcast] Failed for contact {contact.id}: {e}")

        # Update running totals after each batch
        broadcast.sent_count = sent
        broadcast.failed_count = failed
        broadcast.skipped_count = skipped
        db.commit()

        if i + BATCH_SIZE < len(contacts):
            await asyncio.sleep(BATCH_DELAY)

    broadcast.status = BroadcastStatus.COMPLETED
    broadcast.completed_at = datetime.utcnow()
    broadcast.sent_count = sent
    broadcast.failed_count = failed
    broadcast.skipped_count = skipped
    db.commit()

    logger.info(f"[Broadcast] '{broadcast.name}' done — sent={sent}, failed={failed}, skipped={skipped}")


async def _send_whatsapp(db: Session, company_id: int, contact, message: str) -> None:
    from app.services import messaging_service, integration_service

    integration = integration_service.get_integration_by_type_and_company(db, "whatsapp", company_id)
    if not integration:
        raise ValueError("WhatsApp integration not configured.")

    # Personalise: replace {{name}} with contact name
    personalised = message.replace("{{name}}", contact.name or "there")
    await messaging_service.send_whatsapp_message(
        recipient_phone_number=contact.phone_number,
        message_text=personalised,
        integration=integration,
        db=db,
    )


def _send_sms(db: Session, company_id: int, contact, message: str) -> None:
    from app.services import sms_service

    personalised = message.replace("{{name}}", contact.name or "there")
    sms_service.send_sms(to=contact.phone_number, body=personalised, db=db, company_id=company_id)


async def _send_email_broadcast(
    db: Session, company_id: int, contact, subject: Optional[str], message: str
) -> None:
    from app.services import email_service
    from app.models.company_settings import CompanySettings

    settings = db.query(CompanySettings).filter(CompanySettings.company_id == company_id).first()
    if not settings or not settings.smtp_host:
        raise ValueError("SMTP not configured for this company.")

    smtp_config = {
        "host": settings.smtp_host,
        "port": settings.smtp_port or 587,
        "username": settings.smtp_user,
        "password": settings.smtp_password,
        "use_tls": True,
    }
    personalised_body = message.replace("{{name}}", contact.name or "there")
    personalised_subject = (subject or "Message from us").replace("{{name}}", contact.name or "there")

    email_service.send_email_smtp(
        to_email=contact.email,
        subject=personalised_subject,
        text_content=personalised_body,
        html_content=None,
        from_email=settings.smtp_from_email or settings.smtp_user,
        from_name=settings.smtp_from_name or "",
        smtp_config=smtp_config,
    )
