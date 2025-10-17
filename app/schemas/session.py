from typing import Optional
from pydantic import BaseModel, Field

class Session(BaseModel):
    session_id: str = Field(..., alias="conversation_id")
    status: str
    assignee_id: Optional[int] = None
    last_message_timestamp: str
    first_message_content: str
    channel: Optional[str] = None
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    is_client_connected: Optional[bool] = False

    class Config:
        populate_by_name = True
        from_attributes = True
