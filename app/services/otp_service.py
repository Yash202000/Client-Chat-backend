"""
OTP Verification Service

Generates, sends, and validates one-time passwords across:
  - WhatsApp (Meta Cloud API)
  - SMS (Twilio)
  - Email (SMTP)
  - Voice (Twilio call + TwiML read-aloud)
"""
import hashlib
import logging
import random
import string
import uuid
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.models.otp_verification import OTPVerification, OTPChannel, OTPStatus

logger = logging.getLogger(__name__)

OTP_EXPIRES_MINUTES = 10
OTP_MAX_ATTEMPTS = 3
OTP_LENGTH = 6

DEFAULT_TEMPLATE = "Your verification code is {code}. It expires in 10 minutes. Do not share this code with anyone."


def _generate_code() -> str:
    return "".join(random.choices(string.digits, k=OTP_LENGTH))


def _hash_code(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def _format_message(template: Optional[str], code: str) -> str:
    tpl = template or DEFAULT_TEMPLATE
    return tpl.replace("{code}", code)


async def send_otp(
    db: Session,
    company_id: int,
    channel: str,
    recipient: str,
    template: Optional[str] = None,
) -> OTPVerification:
    """Generate and send an OTP. Returns the OTPVerification record."""

    code = _generate_code()
    message = _format_message(template, code)
    verification_id = str(uuid.uuid4())
    expires_at = datetime.utcnow() + timedelta(minutes=OTP_EXPIRES_MINUTES)

    otp = OTPVerification(
        verification_id=verification_id,
        company_id=company_id,
        channel=OTPChannel(channel),
        recipient=recipient,
        code_hash=_hash_code(code),
        status=OTPStatus.PENDING,
        attempts=0,
        expires_at=expires_at,
    )
    db.add(otp)
    db.flush()  # get ID before sending

    try:
        if channel == "whatsapp":
            await _send_via_whatsapp(db, company_id, recipient, message)
        elif channel == "sms":
            _send_via_sms(db, company_id, recipient, message)
        elif channel == "email":
            await _send_via_email(db, company_id, recipient, message)
        elif channel == "voice":
            await _send_via_voice(db, company_id, recipient, code)
        else:
            raise ValueError(f"Unsupported OTP channel: {channel}")
    except Exception as e:
        otp.status = OTPStatus.FAILED
        db.commit()
        logger.error(f"[OTP] Failed to send via {channel} to {recipient}: {e}")
        raise

    db.commit()
    db.refresh(otp)
    return otp


def verify_otp(
    db: Session,
    verification_id: str,
    code: str,
) -> tuple[bool, str]:
    """
    Validate an OTP code.
    Returns (is_valid, message).
    """
    otp = db.query(OTPVerification).filter(
        OTPVerification.verification_id == verification_id
    ).first()

    if not otp:
        return False, "Verification not found."

    if otp.status == OTPStatus.VERIFIED:
        return False, "OTP already used."

    if otp.status == OTPStatus.EXPIRED or datetime.utcnow() > otp.expires_at:
        otp.status = OTPStatus.EXPIRED
        db.commit()
        return False, "OTP has expired."

    if otp.attempts >= OTP_MAX_ATTEMPTS:
        otp.status = OTPStatus.FAILED
        db.commit()
        return False, "Too many failed attempts."

    otp.attempts += 1

    if otp.code_hash != _hash_code(code):
        db.commit()
        remaining = OTP_MAX_ATTEMPTS - otp.attempts
        return False, f"Invalid code. {remaining} attempt(s) remaining."

    otp.status = OTPStatus.VERIFIED
    otp.verified_at = datetime.utcnow()
    db.commit()
    return True, "Verified successfully."


# ---------------------------------------------------------------------------
# Channel senders
# ---------------------------------------------------------------------------

async def _send_via_whatsapp(db: Session, company_id: int, recipient: str, message: str) -> None:
    from app.services import messaging_service, integration_service

    integration = integration_service.get_integration_by_type_and_company(db, "whatsapp", company_id)
    if not integration:
        raise ValueError("WhatsApp integration not configured for this company.")

    await messaging_service.send_whatsapp_message(
        recipient_phone_number=recipient,
        message_text=message,
        integration=integration,
        db=db,
    )
    logger.info(f"[OTP] WhatsApp OTP sent to {recipient}")


def _send_via_sms(db: Session, company_id: int, recipient: str, message: str) -> None:
    from app.services import sms_service

    sms_service.send_sms(to=recipient, body=message, db=db, company_id=company_id)
    logger.info(f"[OTP] SMS OTP sent to {recipient}")


async def _send_via_email(db: Session, company_id: int, recipient: str, message: str) -> None:
    from app.models.company_settings import CompanySettings
    from app.services import email_service

    company_settings = db.query(CompanySettings).filter(
        CompanySettings.company_id == company_id
    ).first()

    if not company_settings or not company_settings.smtp_host:
        raise ValueError("SMTP not configured. Set up email in Settings > Email.")

    smtp_config = {
        "host": company_settings.smtp_host,
        "port": company_settings.smtp_port or 587,
        "user": company_settings.smtp_user,
        "password": company_settings.smtp_password,
        "use_tls": company_settings.smtp_use_tls if company_settings.smtp_use_tls is not None else True,
    }

    await email_service.send_email_smtp(
        to_email=recipient,
        subject="Your verification code",
        text_content=message,
        html_content=f"<p>{message}</p>",
        from_email=company_settings.smtp_from_email,
        from_name=company_settings.smtp_from_name or "Verification",
        smtp_config=smtp_config,
    )
    logger.info(f"[OTP] Email OTP sent to {recipient}")


async def _send_via_voice(db: Session, company_id: int, recipient: str, code: str) -> None:
    """Make a Twilio voice call that reads the OTP aloud via TwiML."""
    from app.core.config import settings
    from app.services import integration_service

    try:
        from twilio.rest import Client as TwilioClient
        from twilio.twiml.voice_response import VoiceResponse
    except ImportError:
        raise ValueError("Twilio library not installed.")

    account_sid = settings.TWILIO_ACCOUNT_SID
    auth_token = settings.TWILIO_AUTH_TOKEN
    from_number = settings.TWILIO_PHONE_NUMBER

    integration = integration_service.get_integration_by_type_and_company(db, "twilio_voice", company_id)
    if integration:
        creds = integration_service.get_decrypted_credentials(integration)
        account_sid = creds.get("account_sid") or account_sid
        auth_token = creds.get("auth_token") or auth_token
        from_number = creds.get("phone_number") or from_number

    if not account_sid or not auth_token or not from_number:
        raise ValueError("Twilio credentials not configured.")

    # Spell out each digit for clarity: "4 8 3 9 2 1"
    spaced_code = " ".join(list(code))
    twiml = VoiceResponse()
    twiml.say(f"Your verification code is, {spaced_code}. I repeat, {spaced_code}.", voice="alice")

    client = TwilioClient(account_sid, auth_token)
    call = client.calls.create(
        twiml=str(twiml),
        to=recipient,
        from_=from_number,
    )
    logger.info(f"[OTP] Voice OTP call initiated to {recipient}, call SID: {call.sid}")


def get_otp_status(db: Session, verification_id: str, company_id: int) -> Optional[OTPVerification]:
    return db.query(OTPVerification).filter(
        OTPVerification.verification_id == verification_id,
        OTPVerification.company_id == company_id,
    ).first()
