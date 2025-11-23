
from sqlalchemy import Column, Integer, String, ForeignKey, Boolean, DateTime, func, Table
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.models.tool import agent_tools

agent_knowledge_bases = Table('agent_knowledge_bases', Base.metadata,
    Column('agent_id', Integer, ForeignKey('agents.id'), primary_key=True),
    Column('knowledge_base_id', Integer, ForeignKey('knowledge_bases.id'), primary_key=True)
)

class Agent(Base):
    __tablename__ = "agents"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    welcome_message = Column(String)
    prompt = Column(String) # System prompt for the agent
    llm_provider = Column(String, default="groq") # e.g., 'groq', 'gemini'
    embedding_model = Column(String, default="gemini") # e.g., 'gemini', 'nvidia', 'nvidia_api'
    model_name = Column(String, default="llama-3.1-8b-instant") # e.g., 'llama-3.1-8b-instant', 'gemini-1.5-flash'
    personality = Column(String, default="helpful")
    language = Column(String, default="en")
    timezone = Column(String, default="UTC")
    is_active = Column(Boolean, default=True)
    response_style = Column(String, nullable=True)
    instructions = Column(String, nullable=True)
    credential_id = Column(Integer, ForeignKey("credentials.id"), nullable=True)
    company_id = Column(Integer, ForeignKey("companies.id"))
    handoff_team_id = Column(Integer, ForeignKey("teams.id"), nullable=True)  # Team to handoff to for human support
    version_number = Column(Integer, default=1)
    parent_version_id = Column(Integer, ForeignKey("agents.id"), nullable=True)
    status = Column(String, default="active") # e.g., active, draft, archived
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    company = relationship("Company", back_populates="agents")
    messages = relationship("ChatMessage", back_populates="agent")
    credential = relationship("Credential")
    handoff_team = relationship("Team", foreign_keys=[handoff_team_id])
    knowledge_bases = relationship("KnowledgeBase", secondary=agent_knowledge_bases, back_populates="agents")
    tools = relationship("Tool", secondary=agent_tools, back_populates="agents")
    webhooks = relationship("Webhook", back_populates="agent")
    workflows = relationship("Workflow", back_populates="agent")
    widget_settings = relationship("WidgetSettings", uselist=False, back_populates="agent")
    parent_version = relationship("Agent", remote_side=[id])
    campaigns = relationship("Campaign", back_populates="agent")
    voice_id = Column(String, nullable=True, default='default')
    tts_provider = Column(String, nullable=False, default='voice_engine')
    stt_provider = Column(String, nullable=False, default='deepgram')
