from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from datetime import datetime
from decimal import Decimal


class CampaignBase(BaseModel):
    name: str
    description: Optional[str] = None
    campaign_type: str  # email, sms, whatsapp, voice, multi_channel
    status: Optional[str] = "draft"
    workflow_id: Optional[int] = None
    agent_id: Optional[int] = None
    owner_user_id: Optional[int] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    scheduled_send_time: Optional[datetime] = None
    target_criteria: Optional[Dict[str, Any]] = None
    goal_type: Optional[str] = None
    goal_value: Optional[int] = None
    budget: Optional[Decimal] = None
    settings: Optional[Dict[str, Any]] = None
    twilio_config: Optional[Dict[str, Any]] = None


class CampaignCreate(CampaignBase):
    pass


class CampaignUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    campaign_type: Optional[str] = None
    status: Optional[str] = None
    workflow_id: Optional[int] = None
    agent_id: Optional[int] = None
    owner_user_id: Optional[int] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    scheduled_send_time: Optional[datetime] = None
    target_criteria: Optional[Dict[str, Any]] = None
    goal_type: Optional[str] = None
    goal_value: Optional[int] = None
    budget: Optional[Decimal] = None
    actual_cost: Optional[Decimal] = None
    settings: Optional[Dict[str, Any]] = None
    twilio_config: Optional[Dict[str, Any]] = None


class Campaign(CampaignBase):
    id: int
    company_id: int
    created_by_user_id: Optional[int] = None
    status: str
    actual_cost: Optional[Decimal] = None
    total_contacts: int
    contacts_reached: int
    contacts_engaged: int
    contacts_converted: int
    total_revenue: Optional[Decimal] = None
    created_at: datetime
    updated_at: datetime
    last_run_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class CampaignWithMessages(Campaign):
    """Campaign with messages included"""
    messages: List[Any] = []  # Will be CampaignMessage schema

    class Config:
        from_attributes = True


class CampaignStats(BaseModel):
    """Campaign statistics"""
    campaign_id: int
    total_contacts: int
    enrolled: int
    active: int
    completed: int
    opted_out: int
    bounced: int
    failed: int
    total_sent: int
    total_delivered: int
    total_opened: int
    total_clicked: int
    total_replied: int
    total_converted: int
    open_rate: float
    click_rate: float
    reply_rate: float
    conversion_rate: float
    total_revenue: Optional[Decimal] = None
    roi: Optional[float] = None


class CampaignEnrollmentRequest(BaseModel):
    """Request to enroll contacts in campaign"""
    contact_ids: List[int]
    enrollment_data: Optional[Dict[str, Any]] = None
