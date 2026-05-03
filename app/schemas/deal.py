from pydantic import BaseModel
from typing import Optional, Dict, Any
from datetime import datetime
from decimal import Decimal


class DealContactSummary(BaseModel):
    id: int
    name: Optional[str] = None
    email: Optional[str] = None

    class Config:
        from_attributes = True


class DealAccountSummary(BaseModel):
    id: int
    name: str

    class Config:
        from_attributes = True


class DealOwnerSummary(BaseModel):
    id: int
    full_name: Optional[str] = None
    email: Optional[str] = None

    class Config:
        from_attributes = True


class DealStageSummary(BaseModel):
    id: int
    name: str
    probability: int
    color: Optional[str] = None

    class Config:
        from_attributes = True


class DealBase(BaseModel):
    title: str
    amount: Optional[Decimal] = None
    currency: str = "USD"
    pipeline_id: int
    stage_id: int
    contact_id: Optional[int] = None
    account_id: Optional[int] = None
    owner_id: Optional[int] = None
    expected_close_date: Optional[datetime] = None
    description: Optional[str] = None
    custom_fields: Optional[Dict[str, Any]] = None


class DealCreate(DealBase):
    pass


class DealUpdate(BaseModel):
    title: Optional[str] = None
    amount: Optional[Decimal] = None
    currency: Optional[str] = None
    stage_id: Optional[int] = None
    pipeline_id: Optional[int] = None
    contact_id: Optional[int] = None
    account_id: Optional[int] = None
    owner_id: Optional[int] = None
    expected_close_date: Optional[datetime] = None
    actual_close_date: Optional[datetime] = None
    status: Optional[str] = None
    won_reason: Optional[str] = None
    lost_reason: Optional[str] = None
    description: Optional[str] = None
    custom_fields: Optional[Dict[str, Any]] = None


class Deal(DealBase):
    id: int
    company_id: int
    status: str
    actual_close_date: Optional[datetime] = None
    won_reason: Optional[str] = None
    lost_reason: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    stage: Optional[DealStageSummary] = None
    contact: Optional[DealContactSummary] = None
    account: Optional[DealAccountSummary] = None
    owner: Optional[DealOwnerSummary] = None

    class Config:
        from_attributes = True
