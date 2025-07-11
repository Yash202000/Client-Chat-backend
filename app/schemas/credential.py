from pydantic import BaseModel
from typing import Optional
import datetime

class CredentialBase(BaseModel):
    platform: str
    api_key: str # This will be excluded from the response model for security

class CredentialCreate(CredentialBase):
    pass

class CredentialUpdate(BaseModel):
    platform: Optional[str] = None
    api_key: Optional[str] = None

class Credential(BaseModel):
    id: int
    platform: str
    created_at: datetime.datetime
    updated_at: datetime.datetime

    class Config:
        orm_mode = True
        exclude = {"api_key"} # Exclude api_key from the response
