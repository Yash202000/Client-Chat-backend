
from pydantic import BaseModel
from typing import Optional

class TeamMembershipBase(BaseModel):
    user_id: int
    team_id: int
    role: str = "member"

class TeamMembershipCreate(TeamMembershipBase):
    pass

class TeamMembershipUpdate(BaseModel):
    role: Optional[str] = None

class TeamMembership(TeamMembershipBase):
    id: int
    company_id: int

    class Config:
        orm_mode = True
