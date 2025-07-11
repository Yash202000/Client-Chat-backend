
from pydantic import BaseModel
from typing import List, Optional
from app.schemas.chat_message import ChatMessage
from app.schemas.webhook import Webhook

from app.schemas.credential import Credential
from app.schemas.knowledge_base import KnowledgeBase

class AgentBase(BaseModel):
    name: str
    welcome_message: Optional[str] = None
    prompt: Optional[str] = None
    personality: Optional[str] = "helpful"
    language: Optional[str] = "en"
    timezone: Optional[str] = "UTC"
    credential_id: Optional[int] = None
    is_active: Optional[bool] = True
    knowledge_base_id: Optional[int] = None

class AgentCreate(AgentBase):
    pass

class AgentUpdate(BaseModel):
    name: Optional[str] = None
    welcome_message: Optional[str] = None
    prompt: Optional[str] = None
    personality: Optional[str] = None
    language: Optional[str] = None
    timezone: Optional[str] = None
    credential_id: Optional[int] = None
    is_active: Optional[bool] = None
    knowledge_base_id: Optional[int] = None

class Agent(AgentBase):
    id: int
    messages: List[ChatMessage] = []
    credential: Optional[Credential] = None
    knowledge_base: Optional[KnowledgeBase] = None
    webhooks: List[Webhook] = []

    class Config:
        orm_mode = True
