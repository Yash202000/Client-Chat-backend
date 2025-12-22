"""
WorkflowTemplate Schemas
Pydantic models for workflow template API
"""
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime


class WorkflowTemplateBase(BaseModel):
    name: str
    description: Optional[str] = None
    category: Optional[str] = None
    icon: Optional[str] = None


class WorkflowTemplateCreate(WorkflowTemplateBase):
    """Schema for creating a new template directly"""
    visual_steps: Dict[str, Any]
    trigger_phrases: Optional[List[str]] = []
    intent_config: Optional[Dict[str, Any]] = None


class WorkflowTemplateFromWorkflow(BaseModel):
    """Schema for saving an existing workflow as a template"""
    workflow_id: int
    name: str
    description: Optional[str] = None
    category: Optional[str] = None
    icon: Optional[str] = None


class WorkflowFromTemplate(BaseModel):
    """Schema for creating a new workflow from a template"""
    name: str
    description: Optional[str] = None


class WorkflowTemplateUpdate(BaseModel):
    """Schema for updating an existing template"""
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    icon: Optional[str] = None
    visual_steps: Optional[Dict[str, Any]] = None
    trigger_phrases: Optional[List[str]] = None
    intent_config: Optional[Dict[str, Any]] = None
    is_active: Optional[bool] = None


class WorkflowTemplateResponse(WorkflowTemplateBase):
    """Full template response with all details"""
    id: int
    visual_steps: Dict[str, Any]
    trigger_phrases: List[str]
    intent_config: Optional[Dict[str, Any]] = None
    is_system: bool
    company_id: Optional[int] = None
    usage_count: int
    created_at: datetime
    updated_at: Optional[datetime] = None
    created_by_name: Optional[str] = None

    class Config:
        from_attributes = True


class WorkflowTemplateListItem(BaseModel):
    """Simplified template for list view"""
    id: int
    name: str
    description: Optional[str] = None
    category: Optional[str] = None
    icon: Optional[str] = None
    is_system: bool
    usage_count: int
    created_at: datetime
    node_count: Optional[int] = None  # Number of nodes in the workflow

    class Config:
        from_attributes = True
