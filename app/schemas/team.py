
from pydantic import BaseModel
from typing import List, Optional
from .team_membership import TeamMembership

class TeamBase(BaseModel):
    name: str

class TeamCreate(TeamBase):
    pass

class TeamUpdate(TeamBase):
    name: Optional[str] = None

class Team(TeamBase):
    id: int
    company_id: int
    members: List[TeamMembership] = []

    class Config:
        orm_mode = True
