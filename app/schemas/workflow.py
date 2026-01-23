from typing import List, Optional, Dict, Any
from pydantic import BaseModel, validator
import json

class WorkflowBase(BaseModel):
    name: str
    description: Optional[str] = None
    agent_ids: Optional[List[int]] = []  # Many-to-many: workflow can be assigned to multiple agents
    trigger_phrases: Optional[List[str]] = None
    intent_config: Optional[Dict[str, Any]] = None
    version: int = 1
    is_active: bool = True
    parent_workflow_id: Optional[int] = None

class WorkflowCreate(WorkflowBase):
    steps: Optional[Dict[str, Any]] = None # Make steps optional
    visual_steps: Optional[Dict[str, Any]] = None

class WorkflowUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    agent_ids: Optional[List[int]] = None  # Many-to-many: workflow can be assigned to multiple agents
    steps: Optional[Dict[str, Any]] = None
    visual_steps: Optional[Dict[str, Any]] = None
    trigger_phrases: Optional[List[str]] = None
    intent_config: Optional[Dict[str, Any]] = None

class Workflow(WorkflowBase):
    id: int
    steps: Dict[str, Any]
    visual_steps: Optional[Dict[str, Any]] = None
    versions: List['Workflow'] = []

    @validator('steps', 'visual_steps', 'intent_config', pre=True, allow_reuse=True)
    def parse_json_strings(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return {}
        return v

    @validator('agent_ids', pre=True, allow_reuse=True)
    def convert_agents_to_ids(cls, v):
        # Handle ORM relationship: if we get Agent objects, extract their IDs
        if v and isinstance(v, list) and len(v) > 0:
            first_item = v[0]
            # Check if this is a list of Agent objects (has 'id' attribute)
            if hasattr(first_item, 'id'):
                return [agent.id for agent in v]
        return v or []

    class Config:
        orm_mode = True
        # Map 'agents' relationship from ORM to 'agent_ids' field
        fields = {'agent_ids': {'alias': 'agents'}}

Workflow.update_forward_refs()
