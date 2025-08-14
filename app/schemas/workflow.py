from typing import List, Optional, Dict, Any
from pydantic import BaseModel, validator
import json

class WorkflowBase(BaseModel):
    name: str
    description: Optional[str] = None
    agent_id: int
    trigger_phrases: Optional[List[str]] = None
    version: int = 1
    is_active: bool = True
    parent_workflow_id: Optional[int] = None

class WorkflowCreate(WorkflowBase):
    steps: Optional[Dict[str, Any]] = None # Make steps optional
    visual_steps: Optional[Dict[str, Any]] = None

class WorkflowUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    agent_id: Optional[int] = None
    steps: Optional[Dict[str, Any]] = None
    visual_steps: Optional[Dict[str, Any]] = None
    trigger_phrases: Optional[List[str]] = None

class Workflow(WorkflowBase):
    id: int
    steps: Dict[str, Any]
    visual_steps: Optional[Dict[str, Any]] = None
    versions: List['Workflow'] = []

    @validator('steps', 'visual_steps', pre=True, allow_reuse=True)
    def parse_json_strings(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return {}
        return v

    class Config:
        orm_mode = True

Workflow.update_forward_refs()
