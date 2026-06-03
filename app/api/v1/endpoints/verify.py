"""
OTP Verification endpoints

POST /verify/send        — generate & send OTP via whatsapp | sms | email | voice
POST /verify/flash-call  — flash call OTP (missed call, last 4 digits of caller ID = code)
POST /verify/check       — validate a code
GET  /verify/{id}        — status check
"""
import logging
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, get_current_active_user
from app.models.user import User
from app.schemas.otp import OTPSendRequest, OTPSendResponse, OTPVerifyRequest, OTPVerifyResponse, OTPStatusResponse
from app.services import otp_service
from app.services import flash_call_service

router = APIRouter()
logger = logging.getLogger(__name__)


class FlashCallRequest(BaseModel):
    recipient: str  # E.164 phone number


@router.post("/send", response_model=OTPSendResponse)
async def send_otp(
    request: OTPSendRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
    x_company_id: int = Header(...),
):
    """Send an OTP to the given recipient via the specified channel."""
    try:
        otp = await otp_service.send_otp(
            db=db,
            company_id=x_company_id,
            channel=request.channel,
            recipient=request.recipient,
            template=request.template,
        )
        return OTPSendResponse(
            verification_id=otp.verification_id,
            channel=otp.channel.value,
            recipient=otp.recipient,
            expires_at=otp.expires_at,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"[OTP] Send error: {e}")
        raise HTTPException(status_code=500, detail="Failed to send OTP. Check channel configuration.")


@router.post("/flash-call", response_model=OTPSendResponse)
async def send_flash_call(
    request: FlashCallRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
    x_company_id: int = Header(...),
):
    """
    Initiate a flash call verification.
    Places a Twilio call that rings briefly then hangs up.
    The last 4 digits of the caller ID are the OTP code.
    """
    try:
        otp = await flash_call_service.send_flash_call(
            db=db,
            company_id=x_company_id,
            recipient=request.recipient,
        )
        return OTPSendResponse(
            verification_id=otp.verification_id,
            channel=otp.channel.value,
            recipient=otp.recipient,
            expires_at=otp.expires_at,
            message="Flash call initiated. Enter the last 4 digits of the missed call number.",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"[FlashCall] Error: {e}")
        raise HTTPException(status_code=500, detail="Flash call failed. Check Twilio configuration.")


@router.post("/check", response_model=OTPVerifyResponse)
def check_otp(
    request: OTPVerifyRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Verify an OTP code."""
    valid, message = otp_service.verify_otp(
        db=db,
        verification_id=request.verification_id,
        code=request.code,
    )
    from datetime import datetime
    return OTPVerifyResponse(
        valid=valid,
        message=message,
        verified_at=datetime.utcnow() if valid else None,
    )


@router.get("/{verification_id}", response_model=OTPStatusResponse)
def get_otp_status(
    verification_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
    x_company_id: int = Header(...),
):
    """Check the status of a verification request."""
    otp = otp_service.get_otp_status(db, verification_id, x_company_id)
    if not otp:
        raise HTTPException(status_code=404, detail="Verification not found.")
    return OTPStatusResponse(
        verification_id=otp.verification_id,
        channel=otp.channel.value,
        recipient=otp.recipient,
        status=otp.status.value,
        attempts=otp.attempts,
        expires_at=otp.expires_at,
        created_at=otp.created_at,
    )
