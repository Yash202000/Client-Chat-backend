from sqlalchemy import Column, Integer, ForeignKey, DateTime, func, UniqueConstraint
from sqlalchemy.orm import relationship
from app.core.database import Base


class PinnedMessage(Base):
    __tablename__ = "pinned_messages"
    __table_args__ = (UniqueConstraint('channel_id', 'message_id', name='uq_pinned_msg'),)

    id = Column(Integer, primary_key=True, index=True)
    channel_id = Column(Integer, ForeignKey("chat_channels.id", ondelete="CASCADE"), nullable=False, index=True)
    message_id = Column(Integer, ForeignKey("internal_chat_messages.id", ondelete="CASCADE"), nullable=False)
    pinned_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    pinned_at = Column(DateTime(timezone=True), server_default=func.now())

    message = relationship("InternalChatMessage")
    pinned_by = relationship("User")
