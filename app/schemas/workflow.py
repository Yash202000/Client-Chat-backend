from typing import List, Optional, Dict, Any
from pydantic import BaseModel

class WorkflowBase(BaseModel):
    name: str
    description: Optional[str] = None
    agent_id: int
    steps: Dict[str, Any] # Stores the executable workflow logic
    visual_steps: Optional[str] = None # Stores the React Flow JSON for visual representation

class WorkflowCreate(WorkflowBase):
    pass

class WorkflowUpdate(WorkflowBase):
    name: Optional[str] = None
    agent_id: Optional[int] = None
    steps: Optional[Dict[str, Any]] = None
    visual_steps: Optional[str] = None

class Workflow(WorkflowBase):
    id: int

    class Config:
        orm_mode = True
