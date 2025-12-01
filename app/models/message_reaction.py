from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, func, UniqueConstraint
from sqlalchemy.orm import relationship
from app.core.database import Base

class MessageReaction(Base):
    __tablename__ = "message_reactions"

    id = Column(Integer, primary_key=True, index=True)

    # Emoji reaction (e.g., "👍", "❤️", "😂", etc.)
    emoji = Column(String, nullable=False)

    # Relationships
    message_id = Column(Integer, ForeignKey("internal_chat_messages.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    message = relationship("InternalChatMessage", back_populates="reactions")
    user = relationship("User")

    # Ensure a user can only react once with the same emoji to a message
    __table_args__ = (
        UniqueConstraint('message_id', 'user_id', 'emoji', name='unique_message_user_emoji'),
    )
