from pydantic import BaseModel
from typing import Optional, Dict, Any
from datetime import datetime


class ContactBase(BaseModel):
    email: Optional[str] = None
    name: Optional[str] = None
    phone_number: Optional[str] = None
    custom_attributes: Optional[Dict[str, Any]] = None
    lead_source: Optional[str] = None
    lifecycle_stage: Optional[str] = None
    do_not_contact: Optional[bool] = False
    opt_in_status: Optional[str] = "unknown"


class ContactCreate(ContactBase):
    pass


class ContactUpdate(ContactBase):
    opt_in_date: Optional[datetime] = None
    opt_out_date: Optional[datetime] = None
    last_contacted_at: Optional[datetime] = None


class Contact(ContactBase):
    id: int
    company_id: int
    do_not_contact: bool
    opt_in_status: str
    opt_in_date: Optional[datetime] = None
    opt_out_date: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    last_contacted_at: Optional[datetime] = None

    class Config:
        from_attributes = True
