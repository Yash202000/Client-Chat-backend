from sqlalchemy import Boolean, Column, Integer, String, JSON, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from app.core.database import Base
import datetime

class ConversationSession(Base):
    __tablename__ = "conversation_sessions"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(String, unique=True, index=True, nullable=False)
    company_id = Column(Integer, ForeignKey("companies.id"))
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=True)
    workflow_id = Column(Integer, ForeignKey("workflows.id"), nullable=True)
    contact_id = Column(Integer, ForeignKey("contacts.id"), nullable=True)
    next_step_id = Column(String, nullable=True) # The ID of the node to execute upon resumption
    
    channel = Column(String, nullable=False, default='web') # e.g., web, whatsapp, messenger
    context = Column(JSON, nullable=False, default={}) # Stores all collected variables
    status = Column(String, nullable=False, default='active') # e.g., active, paused, waiting_for_input, completed
    is_ai_enabled = Column(Boolean, nullable=False, default=True) # Whether the AI should respond automatically
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    company = relationship("Company")
    agent = relationship("Agent")
    workflow = relationship("Workflow")
    contact = relationship("Contact", back_populates="sessions")
    messages = relationship("ChatMessage", back_populates="session")
