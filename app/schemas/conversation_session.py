from typing import Optional, Dict, Any
from pydantic import BaseModel
from datetime import datetime

class ConversationSessionBase(BaseModel):
    conversation_id: str
    workflow_id: Optional[int] = None
    next_step_id: Optional[str] = None
    context: Dict[str, Any] = {}
    status: str = 'active' # e.g., active, paused, waiting_for_input, completed
    is_ai_enabled: bool = True

class ConversationSessionCreate(BaseModel):
    conversation_id: str
    workflow_id: Optional[int] = None
    contact_id: Optional[int] = None
    channel: str
    status: str
    company_id: int
    agent_id: Optional[int] = None


class ConversationSessionUpdate(BaseModel):
    next_step_id: Optional[str] = None
    context: Optional[Dict[str, Any]] = None
    status: Optional[str] = None # e.g., active, paused, waiting_for_input, completed
    rating: Optional[int] = None
    is_ai_enabled: Optional[bool] = None
    assignee_id: Optional[int] = None

    # Handoff fields
    handoff_requested_at: Optional[datetime] = None
    handoff_reason: Optional[str] = None
    assigned_pool: Optional[str] = None
    waiting_for_agent: Optional[bool] = None
    handoff_accepted_at: Optional[datetime] = None

class ConversationSession(ConversationSessionBase):
    id: int

    class Config:
        from_attributes = True
