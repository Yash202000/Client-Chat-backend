from pydantic import BaseModel
from typing import Optional
import datetime

class CredentialBase(BaseModel):
    name: str
    service: str

class CredentialCreate(CredentialBase):
    # This field is for receiving the secret from the user.
    # It will be encrypted by the service and never stored in plain text.
    credentials: str 

class CredentialUpdate(BaseModel):
    name: Optional[str] = None
    service: Optional[str] = None
    # Optionally update the credentials
    credentials: Optional[str] = None

class Credential(CredentialBase):
    id: int
    created_at: datetime.datetime
    updated_at: datetime.datetime

    class Config:
        orm_mode = True
        # Note: `encrypted_credentials` is not included here, so it's never exposed.
