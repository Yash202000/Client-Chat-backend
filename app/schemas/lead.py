from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from datetime import datetime
from decimal import Decimal
from app.schemas.contact import Contact as ContactSchema
from app.schemas.ticket import StatusSummary, TicketTransitionOut, UserSummary


class LeadBase(BaseModel):
    contact_id: int
    assignee_id: Optional[int] = None
    source: Optional[str] = None
    campaign_id: Optional[int] = None
    stage: Optional[str] = None
    workflow_id: Optional[int] = None
    status_id: Optional[int] = None
    qualification_status: Optional[str] = "unqualified"
    qualification_data: Optional[Dict[str, Any]] = None
    score: Optional[int] = 0
    deal_value: Optional[Decimal] = None
    expected_close_date: Optional[datetime] = None
    notes: Optional[str] = None
    tags: Optional[List[str]] = None
    custom_fields: Optional[Dict[str, Any]] = None


class LeadCreate(LeadBase):
    pass


class LeadUpdate(BaseModel):
    contact_id: Optional[int] = None
    assignee_id: Optional[int] = None
    source: Optional[str] = None
    campaign_id: Optional[int] = None
    stage: Optional[str] = None
    qualification_status: Optional[str] = None
    qualification_data: Optional[Dict[str, Any]] = None
    score: Optional[int] = None
    deal_value: Optional[Decimal] = None
    expected_close_date: Optional[datetime] = None
    actual_close_date: Optional[datetime] = None
    won_reason: Optional[str] = None
    lost_reason: Optional[str] = None
    notes: Optional[str] = None
    tags: Optional[List[str]] = None
    custom_fields: Optional[Dict[str, Any]] = None


class Lead(LeadBase):
    id: int
    company_id: int
    workflow_id: Optional[int] = None
    status_id: Optional[int] = None
    stage: Optional[str] = None
    stage_changed_at: Optional[datetime] = None
    previous_stage: Optional[str] = None
    qualification_status: str
    score: int
    last_scored_at: Optional[datetime] = None
    actual_close_date: Optional[datetime] = None
    won_reason: Optional[str] = None
    lost_reason: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    # Workflow-driven fields (populated by service layer)
    status: Optional[StatusSummary] = None
    assignee: Optional[UserSummary] = None
    available_transitions: List[TicketTransitionOut] = []

    class Config:
        from_attributes = True


class LeadWithContact(Lead):
    contact: Optional[ContactSchema] = None

    class Config:
        from_attributes = True


class LeadStageUpdate(BaseModel):
    status_id: Optional[int] = None
    stage: Optional[str] = None
    reason: Optional[str] = None


class LeadAssignment(BaseModel):
    """Schema for assigning lead to user"""
    assignee_id: int
