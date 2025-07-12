from typing import List, Optional, Dict, Any
from pydantic import BaseModel

class WorkflowBase(BaseModel):
    name: str
    description: Optional[str] = None
    agent_id: int
    steps: Dict[str, Any] # Using Dict[str, Any] for flexible step definition

class WorkflowCreate(WorkflowBase):
    pass

class WorkflowUpdate(WorkflowBase):
    name: Optional[str] = None
    agent_id: Optional[int] = None
    steps: Optional[Dict[str, Any]] = None

class Workflow(WorkflowBase):
    id: int

    class Config:
        orm_mode = True
