
from pydantic import BaseModel
from typing import Optional

class TeamMembershipBase(BaseModel):
    user_id: int
    team_id: int
    role: str = "member"

class TeamMembershipCreate(BaseModel):
    user_id: int
    role: str = "member"

class TeamMembershipUpdate(BaseModel):
    role: str

class TeamMembership(TeamMembershipBase):
    id: int
    company_id: int

    class Config:
        orm_mode = True
