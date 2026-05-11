from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from datetime import datetime
from app.schemas.ticket import StatusSummary, TicketTransitionOut


class ContactTagSchema(BaseModel):
    """Schema for tag info embedded in contact response."""
    id: int
    name: str
    color: str

    class Config:
        from_attributes = True


class ContactBase(BaseModel):
    email: Optional[str] = None
    name: Optional[str] = None
    phone_number: Optional[str] = None
    custom_attributes: Optional[Dict[str, Any]] = None
    lead_source: Optional[str] = None
    lifecycle_stage: Optional[str] = None
    do_not_contact: Optional[bool] = False
    opt_in_status: Optional[str] = "unknown"
    account_id: Optional[int] = None
    # Profile fields
    job_title: Optional[str] = None
    company_name: Optional[str] = None
    location: Optional[str] = None
    website: Optional[str] = None
    linkedin_url: Optional[str] = None
    instagram_handle: Optional[str] = None
    facebook_url: Optional[str] = None


class ContactCreate(ContactBase):
    pass


class ContactUpdate(ContactBase):
    opt_in_date: Optional[datetime] = None
    opt_out_date: Optional[datetime] = None
    last_contacted_at: Optional[datetime] = None
    profile_picture_url: Optional[str] = None


class Contact(ContactBase):
    id: int
    company_id: int
    account_id: Optional[int] = None
    workflow_id: Optional[int] = None
    status_id: Optional[int] = None
    do_not_contact: bool
    opt_in_status: str
    opt_in_date: Optional[datetime] = None
    opt_out_date: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    last_contacted_at: Optional[datetime] = None
    tags: Optional[List[ContactTagSchema]] = []
    profile_picture_url: Optional[str] = None
    channel: Optional[str] = None
    wf_status: Optional[StatusSummary] = None
    available_transitions: List[TicketTransitionOut] = []

    class Config:
        from_attributes = True
