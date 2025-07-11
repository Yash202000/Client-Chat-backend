from pydantic import BaseModel
from typing import Optional
import datetime

class ChatMessageBase(BaseModel):
    message: str
    sender: str # 'user' or 'agent'

class ChatMessageCreate(ChatMessageBase):
    pass

class ChatMessage(ChatMessageBase):
    id: int
    session_id: str
    timestamp: datetime.datetime

    class Config:
        orm_mode = True
