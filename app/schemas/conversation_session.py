from typing import Optional, Dict, Any
from pydantic import BaseModel

class ConversationSessionBase(BaseModel):
    conversation_id: str
    workflow_id: Optional[int] = None
    next_step_id: Optional[str] = None
    context: Dict[str, Any] = {}
    status: str = 'active'
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
    status: Optional[str] = None

class ConversationSession(ConversationSessionBase):
    id: int

    class Config:
        from_attributes = True
