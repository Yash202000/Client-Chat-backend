
from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, func, JSON, Boolean, Index
from sqlalchemy.orm import relationship
from app.core.database import Base

class InternalChatMessage(Base):
    __tablename__ = "internal_chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    content = Column(String, nullable=False)

    channel_id = Column(Integer, ForeignKey("chat_channels.id"), nullable=False)
    sender_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    parent_message_id = Column(Integer, ForeignKey("internal_chat_messages.id"), nullable=True)  # For threading

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    scheduled_at = Column(DateTime(timezone=True), nullable=True)

    # To store reactions, read receipts, etc.
    extra_data = Column(JSON, nullable=True)

    channel = relationship("ChatChannel", back_populates="messages")
    sender = relationship("User", back_populates="sent_messages")
    attachments = relationship("ChatAttachment", back_populates="message", cascade="all, delete-orphan")
    reactions = relationship("MessageReaction", back_populates="message", cascade="all, delete-orphan")
    mentions = relationship("MessageMention", back_populates="message", cascade="all, delete-orphan")

    __table_args__ = (
        # Covers the common query: WHERE channel_id = X AND parent_message_id IS NULL ORDER BY created_at DESC
        Index('ix_chat_messages_channel_created', 'channel_id', 'created_at'),
    )

    # Self-referential relationship for threading
    # When a parent message is deleted, its replies are also deleted
    replies = relationship(
        "InternalChatMessage",
        backref="parent",
        remote_side=[id],
        cascade="all, delete",
        foreign_keys=[parent_message_id]
    )
