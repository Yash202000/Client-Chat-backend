from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from app.core.database import Base
import datetime

class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    agent_id = Column(Integer, ForeignKey("agents.id"))
    session_id = Column(String, index=True)
    message = Column(String)
    sender = Column(String) # 'user' or 'agent'
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)
    company_id = Column(Integer, ForeignKey("companies.id"))

    company = relationship("Company") # No back_populates needed here as Company already has messages relationship
    agent = relationship("Agent", back_populates="messages")
