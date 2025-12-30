"""
Pydantic schemas for Twilio voice integration.
"""
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime


# --- Twilio Phone Number Schemas ---

class TwilioPhoneNumberBase(BaseModel):
    """Base schema for Twilio phone number."""
    phone_number: str = Field(..., description="Phone number in E.164 format (e.g., +14155551234)")
    friendly_name: Optional[str] = Field(None, description="Human-readable name for the phone number")
    default_agent_id: Optional[int] = Field(None, description="Default agent to handle calls")
    welcome_message: Optional[str] = Field(None, description="Initial greeting message for callers")
    language: str = Field(default="en-US", description="Language code for speech recognition/synthesis")


class TwilioPhoneNumberCreate(TwilioPhoneNumberBase):
    """Schema for creating a Twilio phone number configuration."""
    integration_id: int = Field(..., description="ID of the Twilio integration")


class TwilioPhoneNumberUpdate(BaseModel):
    """Schema for updating a Twilio phone number configuration."""
    friendly_name: Optional[str] = None
    default_agent_id: Optional[int] = None
    welcome_message: Optional[str] = None
    language: Optional[str] = None
    is_active: Optional[bool] = None


class TwilioPhoneNumberResponse(TwilioPhoneNumberBase):
    """Schema for Twilio phone number response."""
    id: int
    company_id: int
    integration_id: int
    is_active: bool

    class Config:
        from_attributes = True


# --- Voice Call Schemas ---

class VoiceCallBase(BaseModel):
    """Base schema for voice calls."""
    call_sid: str = Field(..., description="Twilio Call SID")
    from_number: str = Field(..., description="Caller's phone number")
    to_number: str = Field(..., description="Called Twilio phone number")


class VoiceCallResponse(VoiceCallBase):
    """Schema for voice call response."""
    id: int
    stream_sid: Optional[str] = None
    company_id: int
    agent_id: Optional[int] = None
    conversation_id: Optional[str] = None
    contact_id: Optional[int] = None
    status: str
    direction: str
    started_at: Optional[datetime] = None
    answered_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    full_transcript: Optional[str] = None

    class Config:
        from_attributes = True


class VoiceCallListResponse(BaseModel):
    """Schema for voice call list response."""
    calls: list[VoiceCallResponse]
    total: int
    skip: int
    limit: int


# --- Twilio Webhook Schemas ---

class TwilioVoiceWebhook(BaseModel):
    """Schema for Twilio voice webhook data."""
    CallSid: str
    AccountSid: str
    From: str = Field(..., alias="From")
    To: str
    CallStatus: str
    ApiVersion: str
    Direction: str
    CallerName: Optional[str] = None
    ForwardedFrom: Optional[str] = None
    FromCity: Optional[str] = None
    FromState: Optional[str] = None
    FromCountry: Optional[str] = None
    ToCity: Optional[str] = None
    ToState: Optional[str] = None
    ToCountry: Optional[str] = None

    class Config:
        populate_by_name = True


class TwilioStatusCallback(BaseModel):
    """Schema for Twilio call status callback."""
    CallSid: str
    CallStatus: str
    CallDuration: Optional[str] = None
    RecordingUrl: Optional[str] = None
    RecordingSid: Optional[str] = None


# --- Media Stream Schemas ---

class MediaStreamMessage(BaseModel):
    """Schema for Twilio Media Stream WebSocket messages."""
    event: str = Field(..., description="Event type: connected, start, media, stop, mark")
    sequenceNumber: Optional[str] = None
    streamSid: Optional[str] = None
    media: Optional[Dict[str, Any]] = None
    start: Optional[Dict[str, Any]] = None
    stop: Optional[Dict[str, Any]] = None
    mark: Optional[Dict[str, Any]] = None


class MediaStreamStart(BaseModel):
    """Schema for Media Stream start event data."""
    streamSid: str
    accountSid: str
    callSid: str
    tracks: list[str]
    customParameters: Optional[Dict[str, str]] = None
    mediaFormat: Optional[Dict[str, Any]] = None


class MediaStreamMedia(BaseModel):
    """Schema for Media Stream media event data."""
    track: str
    chunk: str
    timestamp: str
    payload: str  # Base64 encoded audio


# --- Integration Config Schema ---

class TwilioIntegrationConfig(BaseModel):
    """Schema for Twilio integration credentials configuration."""
    account_sid: str = Field(..., description="Twilio Account SID")
    auth_token: str = Field(..., description="Twilio Auth Token")
    api_key_sid: Optional[str] = Field(None, description="Optional API Key SID")
    api_key_secret: Optional[str] = Field(None, description="Optional API Key Secret")


# --- Response Schemas ---

class TwilioCallConfigResponse(BaseModel):
    """Response schema for call configuration."""
    call_sid: str
    conversation_id: str
    company_id: int
    agent_id: Optional[int]
    welcome_message: Optional[str]
    language: str
