from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime


class SegmentCriteria(BaseModel):
    """Filter criteria for dynamic segments"""
    lifecycle_stages: Optional[List[str]] = None  # ["lead", "mql", "sql"]
    lead_sources: Optional[List[str]] = None  # ["website", "referral"]
    lead_stages: Optional[List[str]] = None  # ["lead", "mql", "opportunity"]
    tag_ids: Optional[List[int]] = None  # [1, 2, 3]
    score_min: Optional[int] = Field(default=None, ge=0, le=100)
    score_max: Optional[int] = Field(default=None, ge=0, le=100)
    opt_in_status: Optional[List[str]] = None  # ["opted_in"]
    include_contacts: Optional[bool] = True
    include_leads: Optional[bool] = True


class SegmentBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    segment_type: Optional[str] = Field(default="dynamic", pattern="^(dynamic|static)$")


class SegmentCreate(SegmentBase):
    criteria: Optional[SegmentCriteria] = None
    static_contact_ids: Optional[List[int]] = None
    static_lead_ids: Optional[List[int]] = None


class SegmentUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    description: Optional[str] = None
    segment_type: Optional[str] = Field(default=None, pattern="^(dynamic|static)$")
    criteria: Optional[SegmentCriteria] = None
    static_contact_ids: Optional[List[int]] = None
    static_lead_ids: Optional[List[int]] = None


class Segment(SegmentBase):
    id: int
    company_id: int
    criteria: Optional[Dict[str, Any]] = None
    static_contact_ids: Optional[List[int]] = None
    static_lead_ids: Optional[List[int]] = None
    contact_count: int = 0
    lead_count: int = 0
    last_refreshed_at: Optional[datetime] = None
    created_by_user_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class SegmentPreview(BaseModel):
    """Preview of segment member counts"""
    contact_count: int
    lead_count: int
    total_count: int


class SegmentMember(BaseModel):
    """A member (contact or lead) of a segment"""
    id: int
    type: str  # 'contact' or 'lead'
    name: Optional[str] = None
    email: Optional[str] = None
    stage: Optional[str] = None
    score: Optional[int] = None


class SegmentMemberList(BaseModel):
    """Paginated list of segment members"""
    members: List[SegmentMember]
    total: int
    page: int
    page_size: int


class SegmentList(BaseModel):
    """Response schema for listing segments"""
    segments: List[Segment]
    total: int
