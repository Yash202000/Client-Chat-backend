from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from decimal import Decimal


class AccountBase(BaseModel):
    name: str
    domain: Optional[str] = None
    industry: Optional[str] = None
    employee_count: Optional[int] = None
    annual_revenue: Optional[Decimal] = None
    phone: Optional[str] = None
    website: Optional[str] = None
    address_street: Optional[str] = None
    address_city: Optional[str] = None
    address_state: Optional[str] = None
    address_country: Optional[str] = None
    address_zip: Optional[str] = None
    description: Optional[str] = None
    owner_id: Optional[int] = None


class AccountCreate(AccountBase):
    pass


class AccountUpdate(BaseModel):
    name: Optional[str] = None
    domain: Optional[str] = None
    industry: Optional[str] = None
    employee_count: Optional[int] = None
    annual_revenue: Optional[Decimal] = None
    phone: Optional[str] = None
    website: Optional[str] = None
    address_street: Optional[str] = None
    address_city: Optional[str] = None
    address_state: Optional[str] = None
    address_country: Optional[str] = None
    address_zip: Optional[str] = None
    description: Optional[str] = None
    owner_id: Optional[int] = None


class AccountContactSummary(BaseModel):
    id: int
    name: Optional[str] = None
    email: Optional[str] = None
    job_title: Optional[str] = None

    class Config:
        from_attributes = True


class AccountOwner(BaseModel):
    id: int
    full_name: Optional[str] = None
    email: Optional[str] = None

    class Config:
        from_attributes = True


class Account(AccountBase):
    id: int
    company_id: int
    created_at: datetime
    updated_at: datetime
    contact_count: Optional[int] = 0
    owner: Optional[AccountOwner] = None

    class Config:
        from_attributes = True


class AccountWithContacts(Account):
    contacts: Optional[List[AccountContactSummary]] = []

    class Config:
        from_attributes = True
