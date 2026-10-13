from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class PhoneNumberBase(BaseModel):
    number: str = Field(..., min_length=2, max_length=32, description="E.164 number (+966...) or short code such as 980")
    friendly_name: Optional[str] = Field(None, max_length=255)
    entry_workflow_id: Optional[int] = Field(None, description="Workflow (IVR) that runs first on inbound calls")
    default_agent_id: Optional[int] = Field(None, description="AI agent that answers when no workflow is set")
    routing_mode: str = Field("ai", pattern="^(ai|direct)$", description="ai: voice process answers; direct: ring agents")
    ring_team_id: Optional[int] = Field(None, description="Team to ring in direct mode (empty = all online users)")
    queue_id: Optional[int] = Field(None, description="Queue (ACD) for this number; takes precedence over ring_team_id")
    language: str = Field("en", max_length=16)
    recording_enabled: bool = True
    is_active: bool = True


class PhoneNumberCreate(PhoneNumberBase):
    provider: str = Field("livekit_sip", pattern="^livekit_sip$")


class PhoneNumberUpdate(BaseModel):
    friendly_name: Optional[str] = Field(None, max_length=255)
    entry_workflow_id: Optional[int] = None
    default_agent_id: Optional[int] = None
    routing_mode: Optional[str] = Field(None, pattern="^(ai|direct)$")
    ring_team_id: Optional[int] = None
    queue_id: Optional[int] = None
    language: Optional[str] = Field(None, max_length=16)
    recording_enabled: Optional[bool] = None
    is_active: Optional[bool] = None


class PhoneNumberResponse(PhoneNumberBase):
    id: int
    company_id: int
    provider: str
    provider_config: Dict[str, Any] = {}
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    # Result of the last LiveKit sync attempt in this request (not stored)
    sync_error: Optional[str] = None

    class Config:
        from_attributes = True


class PhoneNumberListResponse(BaseModel):
    phone_numbers: List[PhoneNumberResponse]
    total: int


class TelephonyStatusResponse(BaseModel):
    livekit_url: str
    livekit_reachable: bool
    error: Optional[str] = None
    inbound_trunks: int = 0
    dispatch_rules: int = 0
    voice_agent_name: str
    fanout_enabled: bool


class CallAcceptResponse(BaseModel):
    call: Dict[str, Any]
    livekit_url: str
    token: str
    room: str


class CallEventResponse(BaseModel):
    seq: int
    type: str
    at: datetime
    actor_type: str
    actor_user_id: Optional[int] = None
    payload: Dict[str, Any] = {}

    class Config:
        from_attributes = True
