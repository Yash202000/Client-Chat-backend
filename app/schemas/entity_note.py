from pydantic import BaseModel, field_validator
from typing import Optional, List
from datetime import datetime
from enum import Enum


class NoteType(str, Enum):
    NOTE = "note"
    CALL = "call"
    MEETING = "meeting"
    EMAIL = "email"
    TASK = "task"


class EntityNoteBase(BaseModel):
    """Base schema for entity notes"""
    note_type: NoteType = NoteType.NOTE
    title: Optional[str] = None
    content: str
    activity_date: Optional[datetime] = None
    duration_minutes: Optional[int] = None
    participants: Optional[List[str]] = None
    outcome: Optional[str] = None


class EntityNoteCreate(EntityNoteBase):
    """Schema for creating a new entity note"""
    contact_id: Optional[int] = None
    lead_id: Optional[int] = None

    @field_validator('content')
    @classmethod
    def content_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError('Content cannot be empty')
        return v.strip()


class EntityNoteUpdate(BaseModel):
    """Schema for updating an entity note"""
    note_type: Optional[NoteType] = None
    title: Optional[str] = None
    content: Optional[str] = None
    activity_date: Optional[datetime] = None
    duration_minutes: Optional[int] = None
    participants: Optional[List[str]] = None
    outcome: Optional[str] = None

    @field_validator('content')
    @classmethod
    def content_not_empty(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.strip():
            raise ValueError('Content cannot be empty')
        return v.strip() if v else v


class EntityNoteResponse(EntityNoteBase):
    """Response schema for entity notes"""
    id: int
    company_id: int
    contact_id: Optional[int] = None
    lead_id: Optional[int] = None
    created_by: int
    creator_email: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class EntityNoteList(BaseModel):
    """Schema for listing entity notes with pagination info"""
    notes: List[EntityNoteResponse]
    total: int
