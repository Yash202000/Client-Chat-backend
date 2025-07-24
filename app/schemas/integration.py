from pydantic import BaseModel
from typing import Dict, Any, Optional

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
