
from pydantic import BaseModel
from typing import List, Optional

class TeamBase(BaseModel):
    name: str

class TeamCreate(TeamBase):
    pass

class TeamUpdate(TeamBase):
    name: Optional[str] = None

class Team(TeamBase):
    id: int
    company_id: int

    class Config:
        orm_mode = True
