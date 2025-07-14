from pydantic import BaseModel
from typing import Optional, Dict, Any

class ContactBase(BaseModel):
    email: Optional[str] = None
    name: Optional[str] = None
    phone_number: Optional[str] = None
    custom_attributes: Optional[Dict[str, Any]] = None

class ContactCreate(ContactBase):
    pass

class ContactUpdate(ContactBase):
    pass

class Contact(ContactBase):
    id: int
    company_id: int

    class Config:
        orm_mode = True
