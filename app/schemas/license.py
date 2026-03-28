"""Schemas for License Management in On-Premise deployments."""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class LicenseActivationRequest(BaseModel):
    """Request to activate a license key."""
    license_key: str


class LicenseGenerateRequest(BaseModel):
    """Request to generate a new license key (admin only)."""
    instance_name: str
    max_users: int = 50
    max_companies: Optional[int] = None
    features: list[str] = []
    expires_in_days: int = 365


class LicensePayload(BaseModel):
    """The decoded payload from a license key."""
    instance_name: str
    max_users: int
    max_companies: Optional[int] = None
    features: list[str] = []
    expires_at: int  # Unix timestamp
    issued_at: int  # Unix timestamp
    iss: str = "HeyGenAlly License Authority"


class LicenseStatusResponse(BaseModel):
    """Response for license status endpoint."""
    mode: str  # "on_premise" | "cloud"
    status: str  # "active" | "expired" | "invalid" | "not_activated"
    instance_name: Optional[str] = None
    max_users: Optional[int] = None
    max_companies: Optional[int] = None
    current_user_count: Optional[int] = None
    current_company_count: Optional[int] = None
    users_remaining: Optional[int] = None
    features: list[str] = []
    expires_at: Optional[datetime] = None
    days_until_expiry: Optional[int] = None
    activated_at: Optional[datetime] = None


class LicenseActivationResponse(BaseModel):
    """Response after activating a license."""
    success: bool
    message: str
    status: LicenseStatusResponse


class LicenseGenerateResponse(BaseModel):
    """Response after generating a license key."""
    license_key: str
    payload: LicensePayload
