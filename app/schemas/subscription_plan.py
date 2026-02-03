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
    description: Optional[str] = None
    billing_interval: Optional[str] = None


class SubscriptionPlan(SubscriptionPlanBase):
    id: int
    created_at: datetime.datetime
    updated_at: datetime.datetime

    class Config:
        from_attributes = True
