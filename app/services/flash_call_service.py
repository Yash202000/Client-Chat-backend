"""
Flash Call Verification Service

How it works:
  1. Pick a Twilio number from the company's pool
  2. The code = last 4 digits of that number's E.164 representation
  3. Place a call from that number to the recipient — hang up immediately via TwiML
  4. User sees a missed call, reads the last 4 digits of the caller ID = their code
  5. They submit those 4 digits to /verify/check as normal

The more numbers a company has in their pool, the more unique codes are possible.
Falls back to the global Twilio number if no pool is configured (less secure but functional).
"""
import hashlib
import logging
import random
import uuid
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.models.otp_verification import OTPVerification, OTPChannel, OTPStatus
from app.models.twilio_phone_number import TwilioPhoneNumber

logger = logging.getLogger(__name__)

FLASH_CALL_EXPIRES_MINUTES = 5  # shorter window — it's a missed call, user reads it instantly
FLASH_CALL_MAX_ATTEMPTS = 3


def _hash_code(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def _pick_caller_number(db: Session, company_id: int) -> tuple[str, str]:
    """
    Pick a Twilio number from the company pool.
    Returns (full_number, last_4_digits).
    Falls back to global settings if no pool exists.
    """
    numbers = db.query(TwilioPhoneNumber).filter(
        TwilioPhoneNumber.company_id == company_id,
        TwilioPhoneNumber.is_active == True,
    ).all()

    if numbers:
        chosen = random.choice(numbers)
        digits_only = "".join(filter(str.isdigit, chosen.phone_number))
        code = digits_only[-4:]
        return chosen.phone_number, code

    # Fallback: global Twilio number from settings
    from app.core.config import settings
    if settings.TWILIO_PHONE_NUMBER:
        digits_only = "".join(filter(str.isdigit, settings.TWILIO_PHONE_NUMBER))
        code = digits_only[-4:]
        return settings.TWILIO_PHONE_NUMBER, code

    raise ValueError("No Twilio phone numbers configured. Add numbers in Settings > Voice > Phone Numbers.")


async def send_flash_call(
    db: Session,
    company_id: int,
    recipient: str,
) -> OTPVerification:
    """
    Initiate a flash call OTP. Places a Twilio call that hangs up immediately.
    The code is the last 4 digits of the caller number.
    """
    from_number, code = _pick_caller_number(db, company_id)

    verification_id = str(uuid.uuid4())
    expires_at = datetime.utcnow() + timedelta(minutes=FLASH_CALL_EXPIRES_MINUTES)

    otp = OTPVerification(
        verification_id=verification_id,
        company_id=company_id,
        channel=OTPChannel.FLASH_CALL,
        recipient=recipient,
        code_hash=_hash_code(code),
        status=OTPStatus.PENDING,
        attempts=0,
        expires_at=expires_at,
    )
    db.add(otp)
    db.flush()

    try:
        _place_flash_call(db, company_id, from_number, recipient)
    except Exception as e:
        otp.status = OTPStatus.FAILED
        db.commit()
        logger.error(f"[FlashCall] Failed to call {recipient}: {e}")
        raise

    db.commit()
    db.refresh(otp)
    logger.info(f"[FlashCall] Flash call sent to {recipient} from {from_number}, code: {code[-2:]}** (last 4 of caller ID)")
    return otp


def _place_flash_call(db: Session, company_id: int, from_number: str, to_number: str) -> None:
    """Place a Twilio call with TwiML that immediately hangs up."""
    from app.core.config import settings
    from app.services import integration_service

    try:
        from twilio.rest import Client as TwilioClient
        from twilio.twiml.voice_response import VoiceResponse
    except ImportError:
        raise ValueError("Twilio library not installed.")

    account_sid = settings.TWILIO_ACCOUNT_SID
    auth_token = settings.TWILIO_AUTH_TOKEN

    integration = integration_service.get_integration_by_type_and_company(db, "twilio_voice", company_id)
    if integration:
        creds = integration_service.get_decrypted_credentials(integration)
        account_sid = creds.get("account_sid") or account_sid
        auth_token = creds.get("auth_token") or auth_token

    if not account_sid or not auth_token:
        raise ValueError("Twilio credentials not configured.")

    # TwiML: ring once then hang up — user sees missed call from our number
    twiml = VoiceResponse()
    twiml.pause(length=1)   # let it ring for ~1 second
    twiml.hangup()

    client = TwilioClient(account_sid, auth_token)
    call = client.calls.create(
        twiml=str(twiml),
        to=to_number,
        from_=from_number,
    )
    logger.info(f"[FlashCall] Call SID: {call.sid}")
