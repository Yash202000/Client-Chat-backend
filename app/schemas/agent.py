
from pydantic import BaseModel, validator
from typing import List, Optional, Dict, Any
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
    model_name: Optional[str] = "llama-3.1-8b-instant"
    personality: Optional[str] = "helpful"
    language: Optional[str] = "en"
    timezone: Optional[str] = "UTC"
    response_style: Optional[str] = None
    instructions: Optional[str] = None
    credential_id: Optional[int] = None
    handoff_team_id: Optional[int] = None  # Team to handoff to for human support
    knowledge_base_ids: Optional[List[int]] = None
    embedding_model: Optional[str] = None
    tool_ids: Optional[List[int]] = []
    voice_id: Optional[str] = 'default'
    tts_provider: Optional[str] = 'voice_engine'
    stt_provider: Optional[str] = 'deepgram'
    vision_enabled: Optional[bool] = False
    # Agent-to-agent handoff configuration
    specialization_topics: Optional[List[Dict[str, str]]] = []
    # Format: [{"topic": "billing", "description": "Handles billing, invoices, payments"}, ...]
    handoff_config: Optional[Dict[str, Any]] = {}
    # Format: {"accept_handoffs": true, "history_mode": "summary", "welcome_message_on_handoff": "..."}

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
    handoff_team_id: Optional[int] = None  # Team to handoff to for human support
    is_active: Optional[bool] = None
    knowledge_base_ids: Optional[List[int]] = None
    model_name: Optional[str] = None
    llm_provider: Optional[str] = None
    embedding_model: Optional[str] = None
    tool_ids: Optional[List[int]] = None
    status: Optional[str] = None
    voice_id: Optional[str] = None
    tts_provider: Optional[str] = None
    stt_provider: Optional[str] = None
    vision_enabled: Optional[bool] = None
    # Agent-to-agent handoff configuration
    specialization_topics: Optional[List[Dict[str, str]]] = None
    handoff_config: Optional[Dict[str, Any]] = None

class Agent(AgentBase):
    id: int
    # messages: List[ChatMessage] = []
    credential: Optional[Credential] = None
    knowledge_bases: List[KnowledgeBase] = []
    webhooks: List[Webhook] = []
    tools: List[Tool] = []
    version_number: int
    parent_version_id: Optional[int] = None
    status: str
    created_at: datetime.datetime
    updated_at: datetime.datetime

    @validator('tool_ids', always=True)
    def populate_tool_ids_from_tools(cls, v, values):
        if 'tools' in values and values['tools']:
            return [tool.id for tool in values['tools']]
        return v

    @validator('knowledge_base_ids', always=True)
    def populate_knowledge_base_ids_from_knowledge_bases(cls, v, values):
        if 'knowledge_bases' in values and values['knowledge_bases']:
            return [kb.id for kb in values['knowledge_bases']]
        return v

    class Config:
        from_attributes = True

class AgentVersion(BaseModel):
    id: int
    version_number: int
    status: str
    created_at: datetime.datetime
    updated_at: datetime.datetime

    class Config:
        from_attributes = True
