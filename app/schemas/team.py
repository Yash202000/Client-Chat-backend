
from pydantic import BaseModel
from typing import List, Optional
from .user import User

class TeamBase(BaseModel):
    name: str

class TeamCreate(TeamBase):
    pass

class TeamUpdate(TeamBase):
    name: Optional[str] = None

class Team(TeamBase):
    id: int
    company_id: int
    members: List[User] = []

    class Config:
        orm_mode = True
