from sqlalchemy import BigInteger, Column, Integer, String, DateTime, ForeignKey, func, JSON
from sqlalchemy.orm import relationship
from app.core.database import Base

class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    message = Column(String)
    sender = Column(String) # 'user' or 'agent'
    message_type = Column(String, default="message") # 'message' or 'note'
    token = Column(String, nullable=True) # For video call tokens, etc.
    attachments = Column(JSON, nullable=True)  # Store attachment metadata (file_name, file_url, file_type, file_size, location)
    options = Column(JSON, nullable=True)  # Store prompt options for message_type='prompt'
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    
    session_id = Column(BigInteger, ForeignKey("conversation_sessions.id"), nullable=False, index=True)
    agent_id = Column(Integer, ForeignKey("agents.id"))
    company_id = Column(Integer, ForeignKey("companies.id"))
    assignee_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    contact_id = Column(Integer, ForeignKey("contacts.id"), nullable=True)
    
    status = Column(String, default="bot") # bot, pending, assigned, resolved
    feedback_rating = Column(Integer, nullable=True)
    feedback_notes = Column(String, nullable=True)
    issue = Column(String, nullable=True, index=True)

    agent = relationship("Agent", back_populates="messages")
    company = relationship("Company")
    assignee = relationship("User")
    contact = relationship("Contact", back_populates="chat_messages")
    session = relationship("ConversationSession", back_populates="messages")
