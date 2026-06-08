"""Company Subscription Schemas for billing and user limit management."""

from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
from enum import Enum


class SubscriptionStatusEnum(str, Enum):
    """Subscription status values."""
    trial = "trial"
    active = "active"
    past_due = "past_due"
    canceled = "canceled"
    expired = "expired"


class CompanySubscriptionBase(BaseModel):
    """Base schema for company subscription."""
    subscription_plan_id: Optional[int] = None
    user_limit: Optional[int] = 5


class CompanySubscriptionCreate(CompanySubscriptionBase):
    """Schema for creating a company subscription."""
    company_id: int


class CompanySubscriptionUpdate(BaseModel):
    """Schema for updating a company subscription."""
    subscription_plan_id: Optional[int] = None
    razorpay_customer_id: Optional[str] = None
    razorpay_subscription_id: Optional[str] = None
    status: Optional[str] = None
    trial_start_date: Optional[datetime] = None
    trial_end_date: Optional[datetime] = None
    current_period_start: Optional[datetime] = None
    current_period_end: Optional[datetime] = None
    user_limit: Optional[int] = None
    addon_seats: Optional[int] = None
    grace_period_end: Optional[datetime] = None
    cancel_at_period_end: Optional[bool] = None


class CompanySubscription(CompanySubscriptionBase):
    """Schema for company subscription response."""
    id: int
    company_id: int
    razorpay_customer_id: Optional[str] = None
    razorpay_subscription_id: Optional[str] = None
    status: str
    trial_start_date: Optional[datetime] = None
    trial_end_date: Optional[datetime] = None
    current_period_start: Optional[datetime] = None
    current_period_end: Optional[datetime] = None
    cancel_at_period_end: bool = False
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class SubscriptionStatus(BaseModel):
    """Response schema for /billing/status endpoint."""
    plan_name: Optional[str] = None
    plan_id: Optional[int] = None
    status: str
    is_trial: bool = False
    trial_days_remaining: Optional[int] = None
    current_period_start: Optional[datetime] = None
    current_period_end: Optional[datetime] = None
    user_limit: int
    current_user_count: int
    users_remaining: int
    addon_seats: int = 0
    addon_seat_cap: int = 0
    addon_seat_price_usd: Optional[float] = None
    addon_seat_price_inr: Optional[float] = None
    warn_threshold: Optional[int] = None
    users_near_limit: bool = False
    grace_period_end: Optional[datetime] = None
    monthly_conversation_count: int = 0
    max_monthly_conversations: Optional[int] = None
    conversations_near_limit: bool = False
    monthly_email_count: int = 0
    max_monthly_emails: Optional[int] = None
    emails_near_limit: bool = False
    total_storage_bytes: int = 0
    max_storage_bytes: Optional[int] = None
    storage_near_limit: bool = False
    cancel_at_period_end: bool = False
    razorpay_customer_id: Optional[str] = None
    plan_features: List[str] = []


class UserLimitUpdate(BaseModel):
    """Schema for admin updating user limit."""
    user_limit: int


class SubscriptionCreateRequest(BaseModel):
    """Schema for creating a Razorpay subscription."""
    plan_id: int


class SubscriptionCreateResponse(BaseModel):
    """Response schema for Razorpay subscription creation."""
    subscription_id: str
    razorpay_key_id: str
    plan_id: str
    plan_name: str
    amount: int
    currency: str
    customer_id: Optional[str] = None
