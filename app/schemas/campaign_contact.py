from pydantic import BaseModel
from typing import Optional, Dict, Any
from datetime import datetime


class CampaignContactBase(BaseModel):
    campaign_id: int
    contact_id: int
    lead_id: Optional[int] = None
    status: Optional[str] = "pending"
    enrollment_data: Optional[Dict[str, Any]] = None


class CampaignContactCreate(CampaignContactBase):
    pass


class CampaignContactUpdate(BaseModel):
    status: Optional[str] = None
    current_step: Optional[int] = None
    current_message_id: Optional[int] = None
    next_scheduled_at: Optional[datetime] = None
    enrollment_data: Optional[Dict[str, Any]] = None
    opt_out_reason: Optional[str] = None


class CampaignContact(CampaignContactBase):
    id: int
    enrolled_at: datetime
    enrolled_by_user_id: Optional[int] = None
    status: str
    current_step: int
    current_message_id: Optional[int] = None
    next_scheduled_at: Optional[datetime] = None
    last_interaction_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    opted_out_at: Optional[datetime] = None
    opt_out_reason: Optional[str] = None
    opens: int
    clicks: int
    replies: int
    conversions: int
    calls_initiated: int
    calls_completed: int
    total_call_duration: int
    voicemails_left: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CampaignContactWithDetails(CampaignContact):
    """Campaign contact with contact and lead details"""
    contact: Optional[Any] = None  # Will be Contact schema
    lead: Optional[Any] = None  # Will be Lead schema

    class Config:
        from_attributes = True
