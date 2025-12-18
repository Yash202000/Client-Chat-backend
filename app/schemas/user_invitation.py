from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime


class UserInvitationCreate(BaseModel):
    email: EmailStr
    role_id: Optional[int] = None


class UserInvitationResponse(BaseModel):
    id: int
    email: str
    role_id: Optional[int] = None
    role_name: Optional[str] = None
    expires_at: datetime
    used_at: Optional[datetime] = None
    created_at: datetime
    invitation_link: str
    invited_by_name: Optional[str] = None

    class Config:
        from_attributes = True


class UserInvitationListItem(BaseModel):
    id: int
    email: str
    role_id: Optional[int] = None
    role_name: Optional[str] = None
    expires_at: datetime
    used_at: Optional[datetime] = None
    created_at: datetime
    invited_by_name: Optional[str] = None
    is_expired: bool = False

    class Config:
        from_attributes = True


class AcceptInvitationRequest(BaseModel):
    token: str
    password: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None


class ValidateInvitationResponse(BaseModel):
    valid: bool
    email: Optional[str] = None
    company_name: Optional[str] = None
    role_name: Optional[str] = None
    expires_at: Optional[datetime] = None
    error: Optional[str] = None
