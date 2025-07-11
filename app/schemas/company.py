
from pydantic import BaseModel
from typing import List
from app.schemas.user import User

class CompanyBase(BaseModel):
    name: str

class CompanyCreate(CompanyBase):
    pass

class Company(CompanyBase):
    id: int
    users: List[User] = []

    class Config:
        orm_mode = True
