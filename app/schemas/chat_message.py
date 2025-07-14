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
    status: str
    assignee_id: Optional[int] = None

    class Config:
        orm_mode = True
