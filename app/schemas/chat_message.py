from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime

class ChatMessageBase(BaseModel):
    message: str
    message_type: str = "message"

class ChatMessageCreate(ChatMessageBase):
    token: Optional[str] = None
    attachments: Optional[List[Dict[str, Any]]] = None  # Attachment metadata
    options: Optional[List[Dict[str, Any]]] = None  # Prompt options for message_type='prompt'

class ChatMessage(ChatMessageBase):
    id: int
    sender: str
    session_id: int
    timestamp: datetime
    agent_id: Optional[int]
    company_id: int
    contact_id: Optional[int] = None  # Can be NULL for anonymous conversations
    token: Optional[str] = None
    status: Optional[str] = None
    assignee_id: Optional[int] = None
    assignee_name: Optional[str] = None  # Name of the agent/user who sent this message
    feedback_rating: Optional[int] = None
    feedback_notes: Optional[str] = None
    issue: Optional[str] = None
    attachments: Optional[List[Dict[str, Any]]] = None  # Attachment metadata (file_name, file_url, file_type, file_size, location)
    options: Optional[List[Dict[str, Any]]] = None  # Prompt options for message_type='prompt'

    model_config = {
        "from_attributes": True
    }