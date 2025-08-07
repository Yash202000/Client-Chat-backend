from pydantic import BaseModel
from typing import Optional, List
import datetime

class SubscriptionPlanBase(BaseModel):
    name: str
    price: float
    currency: Optional[str] = "USD"
    features: Optional[str] = None
    is_active: Optional[bool] = True

class SubscriptionPlanCreate(SubscriptionPlanBase):
    pass

class SubscriptionPlanUpdate(SubscriptionPlanBase):
    name: Optional[str] = None
    price: Optional[float] = None

class SubscriptionPlan(SubscriptionPlanBase):
    id: int
    created_at: datetime.datetime
    updated_at: datetime.datetime

    class Config:
        orm_mode = True
