
from pydantic import BaseModel, HttpUrl
from typing import Optional

class CompanySettingsBase(BaseModel):
    company_name: str
    support_email: str
    timezone: str
    language: str
    business_hours: bool
    logo_url: Optional[HttpUrl] = None
    primary_color: Optional[str] = None
    secondary_color: Optional[str] = None
    custom_domain: Optional[str] = None

class CompanySettingsCreate(CompanySettingsBase):
    pass

class CompanySettingsUpdate(BaseModel):
    company_name: Optional[str] = None
    support_email: Optional[str] = None
    timezone: Optional[str] = None
    language: Optional[str] = None
    business_hours: Optional[bool] = None
    logo_url: Optional[HttpUrl] = None
    primary_color: Optional[str] = None
    secondary_color: Optional[str] = None
    custom_domain: Optional[str] = None

class CompanySettings(CompanySettingsBase):
    id: int

    class Config:
        orm_mode = True
