
from pydantic import BaseModel
from typing import Optional
import datetime
from app.schemas.role import Role

class UserBase(BaseModel):
    email: str

class UserCreate(UserBase):
    password: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone_number: Optional[str] = None
    job_title: Optional[str] = None
    profile_picture_url: Optional[str] = None
    role_id: Optional[int] = None
    is_super_admin: Optional[bool] = False


class UserUpdate(UserBase):
    email: Optional[str] = None
    password: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone_number: Optional[str] = None
    job_title: Optional[str] = None
    profile_picture_url: Optional[str] = None
    is_active: Optional[bool] = None
    is_admin: Optional[bool] = None
    role_id: Optional[int] = None
    subscription_plan_id: Optional[int] = None
    subscription_status: Optional[str] = None
    subscription_start_date: Optional[datetime.datetime] = None
    subscription_end_date: Optional[datetime.datetime] = None

class User(BaseModel):
    id: int
    email: str
    is_active: bool
    company_id: int
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone_number: Optional[str] = None
    job_title: Optional[str] = None
    profile_picture_url: Optional[str] = None
    is_admin: bool
    is_super_admin: bool
    role_id: Optional[int] = None
    role: Optional[Role] = None
    last_login_at: Optional[datetime.datetime] = None
    subscription_plan_id: Optional[int] = None
    subscription_status: Optional[str] = None
    subscription_start_date: Optional[datetime.datetime] = None
    subscription_end_date: Optional[datetime.datetime] = None

    class Config:
        orm_mode = True
        from_attributes = True


class UserWithSuperAdmin(User):
    is_super_admin: bool


class UserInDB(User):
    hashed_password: str
