from typing import Optional, Dict, Any
from pydantic import BaseModel

class ConversationSessionBase(BaseModel):
    conversation_id: str
    workflow_id: int
    next_step_id: Optional[str] = None
    context: Dict[str, Any] = {}
    status: str = 'active'

class ConversationSessionCreate(ConversationSessionBase):
    pass

class ConversationSessionUpdate(BaseModel):
    next_step_id: Optional[str] = None
    context: Optional[Dict[str, Any]] = None
    status: Optional[str] = None

class ConversationSession(ConversationSessionBase):
    id: int

    class Config:
        orm_mode = True
