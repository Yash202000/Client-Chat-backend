
from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Boolean, func
from sqlalchemy.orm import relationship
from app.core.database import Base

class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    notification_type = Column(String, nullable=False)  # 'mention', 'reply', 'reaction', etc.
    title = Column(String, nullable=False)
    message = Column(String, nullable=False)

    # Reference to the entity that triggered the notification
    related_message_id = Column(Integer, ForeignKey("internal_chat_messages.id"), nullable=True)
    related_channel_id = Column(Integer, ForeignKey("chat_channels.id"), nullable=True)

    # Actor who triggered the notification
    actor_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    is_read = Column(Boolean, default=False, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    read_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    user = relationship("User", foreign_keys=[user_id], back_populates="notifications")
    actor = relationship("User", foreign_keys=[actor_id])
    related_message = relationship("InternalChatMessage", foreign_keys=[related_message_id])
    related_channel = relationship("ChatChannel", foreign_keys=[related_channel_id])
