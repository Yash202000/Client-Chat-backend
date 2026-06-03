from pydantic import BaseModel, EmailStr
from typing import Optional, Literal
from datetime import datetime


class OTPSendRequest(BaseModel):
    channel: Literal["whatsapp", "sms", "email", "voice", "flash_call"]
    recipient: str  # phone number (E.164) or email address
    template: Optional[str] = None  # custom message template, use {code} placeholder


class OTPSendResponse(BaseModel):
    verification_id: str
    channel: str
    recipient: str
    expires_at: datetime
    message: str = "OTP sent successfully"


class OTPVerifyRequest(BaseModel):
    verification_id: str
    code: str


class OTPVerifyResponse(BaseModel):
    valid: bool
    message: str
    verified_at: Optional[datetime] = None


class OTPStatusResponse(BaseModel):
    verification_id: str
    channel: str
    recipient: str
    status: str
    attempts: int
    expires_at: datetime
    created_at: datetime
