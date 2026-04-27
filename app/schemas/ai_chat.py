
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime

class AIChatRequest(BaseModel):
    message: str
    conversation_id: Optional[str] = None
    agent_id: Optional[int] = None
    option_key: Optional[str] = None

class AIChatResponse(BaseModel):
    id: int
    message: str
    message_type: str = "message"
    sender: str
    session_id: int
    conversation_id: str
    timestamp: datetime
    agent_id: Optional[int] = None
    options: Optional[List[Dict[str, Any]]] = None
    attachments: Optional[List[Dict[str, Any]]] = None
    execution_steps: List[Dict[str, str]] = []

    model_config = {"from_attributes": True}
