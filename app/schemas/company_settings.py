
from pydantic import BaseModel
from typing import Optional

class CompanySettingsBase(BaseModel):
    company_name: str
    support_email: str
    timezone: str
    language: str
    business_hours: bool
    logo_url: Optional[str] = None
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
    # Token Usage Settings
    token_tracking_mode: Optional[str] = "detailed"  # none, aggregated, detailed
    monthly_budget_cents: Optional[int] = None
    alert_threshold_percent: Optional[int] = 80
    alert_email: Optional[str] = None
    alerts_enabled: Optional[bool] = True
    per_agent_daily_limit_cents: Optional[int] = None

class CompanySettingsCreate(CompanySettingsBase):
    pass

class CompanySettingsUpdate(BaseModel):
    company_name: Optional[str] = None
    support_email: Optional[str] = None
    timezone: Optional[str] = None
    language: Optional[str] = None
    business_hours: Optional[bool] = None
    logo_url: Optional[str] = None
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
    # Token Usage Settings
    token_tracking_mode: Optional[str] = None
    monthly_budget_cents: Optional[int] = None
    alert_threshold_percent: Optional[int] = None
    alert_email: Optional[str] = None
    alerts_enabled: Optional[bool] = None
    per_agent_daily_limit_cents: Optional[int] = None

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
