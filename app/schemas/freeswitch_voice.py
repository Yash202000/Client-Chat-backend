"""
Pydantic schemas for FreeSWITCH voice integration.
"""
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime


# --- FreeSWITCH Phone Number Schemas ---

class FreeSwitchPhoneNumberBase(BaseModel):
    """Base schema for FreeSWITCH phone number/extension."""
    phone_number: str = Field(..., description="Phone number or extension")
    friendly_name: Optional[str] = Field(None, description="Human-readable name")
    default_agent_id: Optional[int] = Field(None, description="Default agent to handle calls")
    welcome_message: Optional[str] = Field(None, description="Initial greeting message for callers")
    language: str = Field(default="en-US", description="Language code for speech recognition/synthesis")
    audio_format: str = Field(default="l16", description="Audio format: l16, PCMU, PCMA")
    sample_rate: int = Field(default=8000, description="Audio sample rate: 8000, 16000, 48000")
    freeswitch_server: Optional[str] = Field(None, description="FreeSWITCH server hostname (for multi-server setups)")


class FreeSwitchPhoneNumberCreate(FreeSwitchPhoneNumberBase):
    """Schema for creating a FreeSWITCH phone number configuration."""
    pass


class FreeSwitchPhoneNumberUpdate(BaseModel):
    """Schema for updating a FreeSWITCH phone number configuration."""
    friendly_name: Optional[str] = None
    default_agent_id: Optional[int] = None
    welcome_message: Optional[str] = None
    language: Optional[str] = None
    audio_format: Optional[str] = None
    sample_rate: Optional[int] = None
    freeswitch_server: Optional[str] = None
    is_active: Optional[bool] = None


class FreeSwitchPhoneNumberResponse(FreeSwitchPhoneNumberBase):
    """Schema for FreeSWITCH phone number response."""
    id: int
    company_id: int
    is_active: bool

    class Config:
        from_attributes = True


class FreeSwitchPhoneNumberListResponse(BaseModel):
    """Schema for FreeSWITCH phone number list response."""
    phone_numbers: list[FreeSwitchPhoneNumberResponse]
    total: int


# --- FreeSWITCH Voice Call Schemas ---

class FreeSwitchCallResponse(BaseModel):
    """Schema for FreeSWITCH voice call response."""
    id: int
    call_uuid: str
    from_number: str
    to_number: str
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


# --- FreeSWITCH WebSocket Message Schemas ---

class FreeSwitchAudioStreamMessage(BaseModel):
    """
    Schema for FreeSWITCH mod_audio_stream WebSocket messages.

    mod_audio_stream sends JSON messages with these events:
    - connect: Initial connection with call info
    - audio: Audio data chunk (base64 L16 PCM)
    - disconnect: Call ended
    """
    event: str = Field(..., description="Event type: connect, audio, disconnect")
    uuid: Optional[str] = Field(None, description="Call UUID")
    audio: Optional[str] = Field(None, description="Base64 encoded L16 audio")
    channel_data: Optional[Dict[str, Any]] = Field(None, description="Channel variables from FreeSWITCH")


class FreeSwitchConnectEvent(BaseModel):
    """Schema for FreeSWITCH connect event data."""
    uuid: str = Field(..., description="Call UUID")
    caller_id_number: Optional[str] = Field(None, description="Caller ID number")
    caller_id_name: Optional[str] = Field(None, description="Caller ID name")
    destination_number: str = Field(..., description="Called number/extension")
    direction: str = Field(default="inbound", description="Call direction")
    channel_data: Optional[Dict[str, Any]] = Field(None, description="Additional channel variables")


class FreeSwitchAudioEvent(BaseModel):
    """Schema for FreeSWITCH audio event data."""
    uuid: str
    audio: str  # Base64 encoded L16 PCM audio


class FreeSwitchDisconnectEvent(BaseModel):
    """Schema for FreeSWITCH disconnect event data."""
    uuid: str
    hangup_cause: Optional[str] = Field(None, description="Hangup cause code")


# --- FreeSWITCH Outbound Audio Response ---

class FreeSwitchAudioResponse(BaseModel):
    """Response to send audio back to FreeSWITCH."""
    event: str = "audio"
    audio: str = Field(..., description="Base64 encoded L16 PCM audio to play")


class FreeSwitchHangupResponse(BaseModel):
    """Response to hang up the call."""
    event: str = "hangup"
    cause: Optional[str] = Field(default="NORMAL_CLEARING", description="Hangup cause")


# --- Integration Config Schema ---

class FreeSwitchIntegrationConfig(BaseModel):
    """
    Schema for FreeSWITCH integration configuration.

    Unlike Twilio, FreeSWITCH typically authenticates via:
    - ESL (Event Socket Library) connection
    - Or by configuring the WebSocket URL in FreeSWITCH dialplan
    """
    esl_host: Optional[str] = Field(None, description="ESL host (if using ESL)")
    esl_port: Optional[int] = Field(None, description="ESL port (default: 8021)")
    esl_password: Optional[str] = Field(None, description="ESL password")
    websocket_secret: Optional[str] = Field(None, description="Optional shared secret for WebSocket auth")
