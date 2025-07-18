from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class ChatMessageBase(BaseModel):
    message: str
    message_type: str = "message"

class ChatMessageCreate(ChatMessageBase):
    pass

class ChatMessage(ChatMessageBase):
    id: int
    sender: str
    session_id: str
    timestamp: datetime
    agent_id: int
    company_id: int
    contact_id: int
    status: Optional[str] = None
    assignee_id: Optional[int] = None
    feedback_rating: Optional[int] = None
    feedback_notes: Optional[str] = None

    class Config:
        from_attributes = True