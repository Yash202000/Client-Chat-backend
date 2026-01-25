"""Company Subscription Schemas for billing and user limit management."""

from pydantic import BaseModel
from typing import Optional
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
    stripe_customer_id: Optional[str] = None
    stripe_subscription_id: Optional[str] = None
    status: Optional[str] = None
    trial_start_date: Optional[datetime] = None
    trial_end_date: Optional[datetime] = None
    current_period_start: Optional[datetime] = None
    current_period_end: Optional[datetime] = None
    user_limit: Optional[int] = None
    cancel_at_period_end: Optional[bool] = None


class CompanySubscription(CompanySubscriptionBase):
    """Schema for company subscription response."""
    id: int
    company_id: int
    stripe_customer_id: Optional[str] = None
    stripe_subscription_id: Optional[str] = None
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
    cancel_at_period_end: bool = False
    stripe_customer_id: Optional[str] = None


class UserLimitUpdate(BaseModel):
    """Schema for admin updating user limit."""
    user_limit: int


class CheckoutSessionCreate(BaseModel):
    """Schema for creating a checkout session."""
    plan_id: int


class CheckoutSessionResponse(BaseModel):
    """Response schema for checkout session creation."""
    url: str
    session_id: str


class PortalSessionResponse(BaseModel):
    """Response schema for Stripe portal session."""
    url: str
