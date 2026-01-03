from pydantic import BaseModel
from typing import Dict, Any, Optional, Literal
from datetime import datetime


class IntegrationBase(BaseModel):
    name: str
    type: str
    enabled: bool = True


class IntegrationCreate(IntegrationBase):
    # Credentials will be a JSON object from the frontend, e.g.,
    # {"api_token": "...", "phone_number_id": "..."}
    credentials: Dict[str, Any]


class IntegrationUpdate(BaseModel):
    name: Optional[str] = None
    enabled: Optional[bool] = None
    credentials: Optional[Dict[str, Any]] = None


class Integration(IntegrationBase):
    id: int
    company_id: int

    # We don't expose credentials on read operations for security.
    # A separate endpoint can be used to check status if needed.

    class Config:
        from_attributes = True


# WhatsApp OAuth-specific schemas

class WhatsAppOAuthSetup(BaseModel):
    """Schema for setting up WhatsApp OAuth credentials."""
    access_token: str  # Initial short-lived or long-lived token
    client_id: str  # Meta App ID
    client_secret: str  # Meta App Secret
    phone_number_id: str  # WhatsApp Business phone number ID
    whatsapp_business_number: Optional[str] = None  # Display number (optional)


class WhatsAppOAuthStatus(BaseModel):
    """Schema for WhatsApp OAuth token status response."""
    integration_id: int
    integration_name: str
    is_oauth_enabled: bool
    token_type: Literal["short_lived", "long_lived", "legacy"]
    needs_refresh: bool
    refresh_error: Optional[str] = None
    token_expires_at: Optional[str] = None  # ISO format datetime
    hours_until_expiry: Optional[float] = None
    last_refresh_at: Optional[str] = None  # ISO format datetime


class WhatsAppOAuthCredentials(BaseModel):
    """
    Schema for WhatsApp OAuth credentials stored in the database.
    Used for validation when reading/writing credentials.
    """
    # Required for all integrations
    access_token: str
    phone_number_id: str

    # OAuth-specific fields (optional for backward compatibility)
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    whatsapp_business_number: Optional[str] = None
    token_type: Literal["short_lived", "long_lived", "legacy"] = "legacy"
    token_expires_at: Optional[int] = None  # Unix timestamp
    last_refresh_at: Optional[int] = None  # Unix timestamp
    refresh_error: Optional[str] = None

    def is_oauth_enabled(self) -> bool:
        """Check if this integration has OAuth credentials configured."""
        return bool(self.client_id and self.client_secret)

    def is_token_expired(self, buffer_seconds: int = 300) -> bool:
        """Check if token is expired or will expire within buffer period."""
        if not self.token_expires_at:
            return False  # Legacy tokens don't track expiry
        return datetime.utcnow().timestamp() + buffer_seconds >= self.token_expires_at
