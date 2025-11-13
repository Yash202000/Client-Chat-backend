from sqlalchemy import Column, Integer, ForeignKey, DateTime, func
from sqlalchemy.orm import relationship
from app.core.database import Base

class MessageMention(Base):
    __tablename__ = "message_mentions"

    id = Column(Integer, primary_key=True, index=True)

    # The message that contains the mention
    message_id = Column(Integer, ForeignKey("internal_chat_messages.id"), nullable=False)

    # The user who was mentioned
    mentioned_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    message = relationship("InternalChatMessage", back_populates="mentions")
    mentioned_user = relationship("User", foreign_keys=[mentioned_user_id])
