
from pydantic import BaseModel
from typing import Optional

class AIChatRequest(BaseModel):
    message: str
    conversation_id: Optional[str] = None
    agent_id: Optional[int] = None
