
from sqlalchemy import Column, Integer, String, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.models.tool import agent_tools

class Agent(Base):
    __tablename__ = "agents"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    welcome_message = Column(String)
    prompt = Column(String) # System prompt for the agent
    personality = Column(String, default="helpful")
    language = Column(String, default="en")
    timezone = Column(String, default="UTC")
    is_active = Column(Boolean, default=True)
    response_style = Column(String, nullable=True)
    instructions = Column(String, nullable=True)
    credential_id = Column(Integer, ForeignKey("credentials.id"), nullable=True)
    knowledge_base_id = Column(Integer, ForeignKey("knowledge_bases.id"), nullable=True)
    company_id = Column(Integer, ForeignKey("companies.id"))

    company = relationship("Company", back_populates="agents")
    messages = relationship("ChatMessage", back_populates="agent")
    credential = relationship("Credential")
    knowledge_base = relationship("KnowledgeBase")
    tools = relationship("Tool", secondary=agent_tools, back_populates="agents")
    webhooks = relationship("Webhook", back_populates="agent")
    workflows = relationship("Workflow", back_populates="agent")
