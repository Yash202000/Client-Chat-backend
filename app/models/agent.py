
from sqlalchemy import Column, Integer, String, ForeignKey, Boolean, DateTime
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.models.tool import agent_tools
import datetime

class Agent(Base):
    __tablename__ = "agents"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    welcome_message = Column(String)
    prompt = Column(String) # System prompt for the agent
    llm_provider = Column(String, default="groq") # e.g., 'groq', 'gemini'
    model_name = Column(String, default="llama3-8b-8192") # e.g., 'llama3-8b-8192', 'gemini-1.5-flash'
    personality = Column(String, default="helpful")
    language = Column(String, default="en")
    timezone = Column(String, default="UTC")
    is_active = Column(Boolean, default=True)
    response_style = Column(String, nullable=True)
    instructions = Column(String, nullable=True)
    credential_id = Column(Integer, ForeignKey("credentials.id"), nullable=True)
    knowledge_base_id = Column(Integer, ForeignKey("knowledge_bases.id"), nullable=True)
    company_id = Column(Integer, ForeignKey("companies.id"))
    version_number = Column(Integer, default=1)
    parent_version_id = Column(Integer, ForeignKey("agents.id"), nullable=True)
    status = Column(String, default="active") # e.g., active, draft, archived
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    company = relationship("Company", back_populates="agents")
    messages = relationship("ChatMessage", back_populates="agent")
    credential = relationship("Credential")
    knowledge_base = relationship("KnowledgeBase")
    tools = relationship("Tool", secondary=agent_tools, back_populates="agents")
    webhooks = relationship("Webhook", back_populates="agent")
    workflows = relationship("Workflow", back_populates="agent")
    widget_settings = relationship("WidgetSettings", uselist=False, back_populates="agent")
    parent_version = relationship("Agent", remote_side=[id])
    voice_id = Column(String, nullable=True, default='default')
    tts_provider = Column(String, nullable=False, default='voice_engine')
    stt_provider = Column(String, nullable=False, default='deepgram')
