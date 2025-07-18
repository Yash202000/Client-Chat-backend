from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, func
from sqlalchemy.orm import relationship
from app.core.database import Base
import datetime

class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String, index=True)
    message = Column(String)
    sender = Column(String) # 'user' or 'agent'
    message_type = Column(String, default="message") # 'message' or 'note'
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    
    agent_id = Column(Integer, ForeignKey("agents.id"))
    company_id = Column(Integer, ForeignKey("companies.id"))
    assignee_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    contact_id = Column(Integer, ForeignKey("contacts.id"), nullable=True)
    
    status = Column(String, default="bot") # bot, pending, assigned, resolved
    feedback_rating = Column(Integer, nullable=True)
    feedback_notes = Column(String, nullable=True)

    agent = relationship("Agent", back_populates="messages")
    company = relationship("Company")
    assignee = relationship("User")
    contact = relationship("Contact", back_populates="chat_messages")
