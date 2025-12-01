from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


class TagBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    color: Optional[str] = Field(default="#6B7280", pattern="^#[0-9A-Fa-f]{6}$")
    description: Optional[str] = Field(default=None, max_length=255)
    entity_type: Optional[str] = Field(default="both", pattern="^(lead|contact|both)$")


class TagCreate(TagBase):
    pass


class TagUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    color: Optional[str] = Field(default=None, pattern="^#[0-9A-Fa-f]{6}$")
    description: Optional[str] = Field(default=None, max_length=255)
    entity_type: Optional[str] = Field(default=None, pattern="^(lead|contact|both)$")


class Tag(TagBase):
    id: int
    company_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class TagWithCounts(Tag):
    """Tag with usage counts"""
    lead_count: int = 0
    contact_count: int = 0


class TagAssign(BaseModel):
    """Schema for bulk assigning/unassigning tags"""
    lead_ids: Optional[List[int]] = None
    contact_ids: Optional[List[int]] = None


class TagList(BaseModel):
    """Response schema for listing tags"""
    tags: List[TagWithCounts]
    total: int
