
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
    # SMTP Settings
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = 587
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    smtp_use_tls: Optional[bool] = True
    smtp_from_email: Optional[str] = None
    smtp_from_name: Optional[str] = None

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
    # SMTP Settings
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = None
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    smtp_use_tls: Optional[bool] = None
    smtp_from_email: Optional[str] = None
    smtp_from_name: Optional[str] = None

class CompanySettings(CompanySettingsBase):
    id: int

    class Config:
        orm_mode = True


class SMTPTestRequest(BaseModel):
    """Request to test SMTP configuration"""
    to_email: str
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = None
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    smtp_use_tls: Optional[bool] = None
    smtp_from_email: Optional[str] = None
    smtp_from_name: Optional[str] = None
