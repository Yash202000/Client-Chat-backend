from pydantic import BaseModel, Field
from typing import Optional

class WebSocketSessionUpdate(BaseModel):
    session_id: str = Field(..., alias="conversation_id")

    class Config:
        populate_by_name = True
        from_attributes = True

class WebSocketMessage(BaseModel):
    type: str
    session: WebSocketSessionUpdate
