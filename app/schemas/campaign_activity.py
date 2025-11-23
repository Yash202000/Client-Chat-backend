from pydantic import BaseModel
from typing import Optional, Dict, Any
from datetime import datetime
from decimal import Decimal


class CampaignActivityBase(BaseModel):
    campaign_id: int
    contact_id: int
    lead_id: Optional[int] = None
    message_id: Optional[int] = None
    activity_type: str
    activity_data: Optional[Dict[str, Any]] = None
    revenue_amount: Optional[Decimal] = None
    external_id: Optional[str] = None
    session_id: Optional[str] = None
    error_message: Optional[str] = None
    error_code: Optional[str] = None


class CampaignActivityCreate(CampaignActivityBase):
    pass


class CampaignActivity(CampaignActivityBase):
    id: int
    timestamp: datetime

    class Config:
        from_attributes = True


class CampaignActivityWithDetails(CampaignActivity):
    """Campaign activity with contact and lead details"""
    contact: Optional[Any] = None  # Will be Contact schema
    lead: Optional[Any] = None  # Will be Lead schema
    message: Optional[Any] = None  # Will be CampaignMessage schema

    class Config:
        from_attributes = True
