"""
Cash on Delivery (COD) Verification Service

Flow:
  1. Merchant calls POST /cod/verify with order details + customer phone
  2. System sends WhatsApp/SMS: "Confirm ₹1,200 order for Blue Shoes? Reply YES or NO"
  3. Customer replies YES or NO
  4. Incoming webhook (WhatsApp or SMS) calls handle_cod_reply()
  5. Status updates + optional webhook fires to merchant
"""
import logging
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional

import httpx
from sqlalchemy.orm import Session

from app.models.cod_verification import CODVerification, CODChannel, CODStatus

logger = logging.getLogger(__name__)

COD_EXPIRES_MINUTES = 30
YES_KEYWORDS = {"yes", "y", "confirm", "ok", "okay", "haan", "ha", "1"}
NO_KEYWORDS = {"no", "n", "cancel", "nahi", "nope", "0"}


def _build_message(verification: CODVerification) -> str:
    amount_str = ""
    if verification.order_amount:
        symbol = "₹" if verification.currency == "INR" else verification.currency
        amount_str = f" for {symbol}{verification.order_amount:,.0f}"

    name_str = f" Hi {verification.customer_name}," if verification.customer_name else ""
    order_str = f" (Order #{verification.order_id})"

    return (
        f"{name_str} Your Cash on Delivery order{amount_str}{order_str} is ready to be placed. "
        f"Reply *YES* to confirm or *NO* to cancel."
    )


async def create_cod_verification(
    db: Session,
    company_id: int,
    order_id: str,
    channel: str,
    recipient: str,
    order_amount: Optional[Decimal] = None,
    currency: str = "INR",
    customer_name: Optional[str] = None,
    webhook_url: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> CODVerification:
    """Send a COD confirmation request to the customer."""
    verification_id = str(uuid.uuid4())
    expires_at = datetime.utcnow() + timedelta(minutes=COD_EXPIRES_MINUTES)

    cod = CODVerification(
        verification_id=verification_id,
        company_id=company_id,
        order_id=order_id,
        order_amount=order_amount,
        currency=currency,
        customer_name=customer_name,
        channel=CODChannel(channel),
        recipient=recipient,
        status=CODStatus.PENDING,
        expires_at=expires_at,
        webhook_url=webhook_url,
        extra_data=metadata,
    )
    db.add(cod)
    db.flush()

    message = _build_message(cod)

    try:
        if channel == "whatsapp":
            await _send_whatsapp(db, company_id, recipient, message)
        elif channel == "sms":
            _send_sms(db, company_id, recipient, message)
        else:
            raise ValueError(f"Unsupported COD channel: {channel}")
    except Exception as e:
        cod.status = CODStatus.FAILED
        db.commit()
        logger.error(f"[COD] Failed to send to {recipient}: {e}")
        raise

    db.commit()
    db.refresh(cod)
    logger.info(f"[COD] Verification sent — order {order_id}, recipient {recipient}")
    return cod


async def handle_cod_reply(
    db: Session,
    company_id: int,
    sender_phone: str,
    message_text: str,
) -> bool:
    """
    Called by the WhatsApp/SMS webhook when a message is received.
    Checks if the sender has a pending COD verification and processes YES/NO.
    Returns True if the message was consumed by COD (caller should skip normal flow).
    """
    normalized = message_text.strip().lower()

    # Find the most recent pending COD for this recipient + company
    cod = (
        db.query(CODVerification)
        .filter(
            CODVerification.company_id == company_id,
            CODVerification.recipient == sender_phone,
            CODVerification.status == CODStatus.PENDING,
            CODVerification.expires_at > datetime.utcnow(),
        )
        .order_by(CODVerification.created_at.desc())
        .first()
    )

    if not cod:
        return False  # no pending COD — let normal message flow continue

    cod.customer_reply = message_text.strip()
    cod.replied_at = datetime.utcnow()

    if normalized in YES_KEYWORDS:
        cod.status = CODStatus.CONFIRMED
        ack = "✅ Your order has been confirmed! We'll process it shortly."
    elif normalized in NO_KEYWORDS:
        cod.status = CODStatus.CANCELLED
        ack = "❌ Your order has been cancelled. Let us know if you need anything else."
    else:
        # Ambiguous reply — ask again, don't consume the message
        return False

    db.commit()
    logger.info(f"[COD] Order {cod.order_id} → {cod.status.value} (reply: '{cod.customer_reply}')")

    # Send acknowledgement back to customer
    try:
        if cod.channel == CODChannel.WHATSAPP:
            await _send_whatsapp(db, company_id, sender_phone, ack)
        elif cod.channel == CODChannel.SMS:
            _send_sms(db, company_id, sender_phone, ack)
    except Exception as e:
        logger.warning(f"[COD] Ack send failed: {e}")

    # Fire webhook to merchant if configured
    if cod.webhook_url:
        await _fire_webhook(cod)

    return True  # message consumed — skip normal chat/agent flow


async def expire_old_cod_verifications(db: Session) -> int:
    """Mark expired pending COD verifications. Call from scheduler."""
    result = (
        db.query(CODVerification)
        .filter(
            CODVerification.status == CODStatus.PENDING,
            CODVerification.expires_at <= datetime.utcnow(),
        )
        .all()
    )
    for cod in result:
        cod.status = CODStatus.EXPIRED
    db.commit()
    if result:
        logger.info(f"[COD] Expired {len(result)} pending verifications")
    return len(result)


def get_cod_status(db: Session, verification_id: str, company_id: int) -> Optional[CODVerification]:
    return db.query(CODVerification).filter(
        CODVerification.verification_id == verification_id,
        CODVerification.company_id == company_id,
    ).first()


def list_cod_verifications(
    db: Session,
    company_id: int,
    order_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
):
    q = db.query(CODVerification).filter(CODVerification.company_id == company_id)
    if order_id:
        q = q.filter(CODVerification.order_id == order_id)
    if status:
        q = q.filter(CODVerification.status == CODStatus(status))
    return q.order_by(CODVerification.created_at.desc()).offset(offset).limit(limit).all()


# ---------------------------------------------------------------------------
# Internal senders
# ---------------------------------------------------------------------------

async def _send_whatsapp(db: Session, company_id: int, recipient: str, message: str) -> None:
    from app.services import messaging_service, integration_service

    integration = integration_service.get_integration_by_type_and_company(db, "whatsapp", company_id)
    if not integration:
        raise ValueError("WhatsApp integration not configured.")
    await messaging_service.send_whatsapp_message(recipient, message, integration, db)


def _send_sms(db: Session, company_id: int, recipient: str, message: str) -> None:
    from app.services import sms_service
    sms_service.send_sms(to=recipient, body=message, db=db, company_id=company_id)


async def _fire_webhook(cod: CODVerification) -> None:
    payload = {
        "event": "cod.reply",
        "verification_id": cod.verification_id,
        "order_id": cod.order_id,
        "status": cod.status.value,
        "customer_reply": cod.customer_reply,
        "replied_at": cod.replied_at.isoformat() if cod.replied_at else None,
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(cod.webhook_url, json=payload)
        logger.info(f"[COD] Webhook fired to {cod.webhook_url} for order {cod.order_id}")
    except Exception as e:
        logger.warning(f"[COD] Webhook delivery failed to {cod.webhook_url}: {e}")
