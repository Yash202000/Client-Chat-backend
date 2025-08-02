
from pydantic import BaseModel
from typing import List, Optional
from app.schemas.chat_message import ChatMessage
from app.schemas.webhook import Webhook
from app.schemas.credential import Credential
from app.schemas.knowledge_base import KnowledgeBase
from app.schemas.tool import Tool
import datetime

class AgentBase(BaseModel):
    name: str
    welcome_message: str
    prompt: str
    llm_provider: Optional[str] = "groq"
    model_name: Optional[str] = "llama3-8b-8192"
    personality: Optional[str] = "helpful"
    language: Optional[str] = "en"
    timezone: Optional[str] = "UTC"
    response_style: Optional[str] = None
    instructions: Optional[str] = None
    credential_id: Optional[int] = None
    knowledge_base_id: Optional[int] = None
    tool_ids: Optional[List[int]] = []
    voice_id: Optional[str] = 'default'
    tts_provider: Optional[str] = 'voice_engine'
    stt_provider: Optional[str] = 'deepgram'

class AgentCreate(AgentBase):
    pass

class AgentUpdate(BaseModel):
    name: Optional[str] = None
    welcome_message: Optional[str] = None
    prompt: Optional[str] = None
    personality: Optional[str] = None
    language: Optional[str] = None
    timezone: Optional[str] = None
    response_style: Optional[str] = None
    instructions: Optional[str] = None
    credential_id: Optional[int] = None
    is_active: Optional[bool] = None
    knowledge_base_id: Optional[int] = None
    tool_ids: Optional[List[int]] = None
    status: Optional[str] = None
    voice_id: Optional[str] = None
    tts_provider: Optional[str] = None
    stt_provider: Optional[str] = None

class Agent(AgentBase):
    id: int
    messages: List[ChatMessage] = []
    credential: Optional[Credential] = None
    knowledge_base: Optional[KnowledgeBase] = None
    webhooks: List[Webhook] = []
    tools: List[Tool] = []
    version_number: int
    parent_version_id: Optional[int] = None
    status: str
    created_at: datetime.datetime
    updated_at: datetime.datetime

    class Config:
        from_attributes = True

