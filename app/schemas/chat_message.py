from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class ChatMessageBase(BaseModel):
    message: str
    message_type: str = "message"

class ChatMessageCreate(ChatMessageBase):
    token: Optional[str] = None

class ChatMessage(ChatMessageBase):
    id: int
    sender: str
    session_id: str
    timestamp: datetime
    agent_id: Optional[int]
    company_id: int
    contact_id: int
    token: Optional[str] = None
    status: Optional[str] = None
    assignee_id: Optional[int] = None
    feedback_rating: Optional[int] = None
    feedback_notes: Optional[str] = None

    model_config = {
        "from_attributes": True
    }