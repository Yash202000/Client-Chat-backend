from pydantic import BaseModel
from typing import Optional
import datetime


class SubscriptionPlanBase(BaseModel):
    name: str
    price: float
    currency: Optional[str] = "INR"
    features: Optional[str] = None
    is_active: Optional[bool] = True
    # Razorpay fields
    razorpay_plan_id: Optional[str] = None
    # User limit and trial configuration
    default_user_limit: Optional[int] = 5
    trial_days: Optional[int] = 14
    # User limit enforcement
    warn_threshold: Optional[int] = None
    addon_seat_cap: Optional[int] = 0
    addon_seat_price_usd: Optional[float] = None
    addon_seat_price_inr: Optional[float] = None
    grace_period_days: Optional[int] = 0
    # Agent limits
    max_agents: Optional[int] = None
    max_active_agents: Optional[int] = None
    max_monthly_conversations: Optional[int] = None
    max_kb_upload_bytes: Optional[int] = None
    max_knowledge_bases: Optional[int] = None
    max_channels: Optional[int] = None
    max_contacts: Optional[int] = None
    max_leads: Optional[int] = None
    max_workflows: Optional[int] = None
    max_campaigns: Optional[int] = None
    max_monthly_emails: Optional[int] = None
    max_storage_bytes: Optional[int] = None
    # Plan details
    description: Optional[str] = None
    billing_interval: Optional[str] = "month"


class SubscriptionPlanCreate(SubscriptionPlanBase):
    pass


class SubscriptionPlanUpdate(BaseModel):
    name: Optional[str] = None
    price: Optional[float] = None
    currency: Optional[str] = None
    features: Optional[str] = None
    is_active: Optional[bool] = None
    razorpay_plan_id: Optional[str] = None
    default_user_limit: Optional[int] = None
    trial_days: Optional[int] = None
    warn_threshold: Optional[int] = None
    addon_seat_cap: Optional[int] = None
    addon_seat_price_usd: Optional[float] = None
    addon_seat_price_inr: Optional[float] = None
    grace_period_days: Optional[int] = None
    max_agents: Optional[int] = None
    max_active_agents: Optional[int] = None
    max_monthly_conversations: Optional[int] = None
    max_kb_upload_bytes: Optional[int] = None
    max_knowledge_bases: Optional[int] = None
    max_channels: Optional[int] = None
    max_contacts: Optional[int] = None
    max_leads: Optional[int] = None
    max_workflows: Optional[int] = None
    max_campaigns: Optional[int] = None
    max_monthly_emails: Optional[int] = None
    max_storage_bytes: Optional[int] = None
    description: Optional[str] = None
    billing_interval: Optional[str] = None


class SubscriptionPlan(SubscriptionPlanBase):
    id: int
    created_at: datetime.datetime
    updated_at: datetime.datetime

    class Config:
        from_attributes = True
