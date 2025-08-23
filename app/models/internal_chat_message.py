
from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, func, JSON
from sqlalchemy.orm import relationship
from app.core.database import Base

class InternalChatMessage(Base):
    __tablename__ = "internal_chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    content = Column(String, nullable=False)
    
    channel_id = Column(Integer, ForeignKey("chat_channels.id"), nullable=False)
    sender_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # To store reactions, read receipts, etc.
    extra_data = Column(JSON, nullable=True)

    channel = relationship("ChatChannel", back_populates="messages")
    sender = relationship("User", back_populates="sent_messages")
