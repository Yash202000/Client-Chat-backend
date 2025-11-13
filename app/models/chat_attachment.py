from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, func, BigInteger
from sqlalchemy.orm import relationship
from app.core.database import Base

class ChatAttachment(Base):
    __tablename__ = "chat_attachments"

    id = Column(Integer, primary_key=True, index=True)

    # File information
    file_name = Column(String, nullable=False)
    file_url = Column(String, nullable=False)  # S3 URL or path
    file_type = Column(String, nullable=False)  # MIME type (e.g., 'image/png', 'application/pdf')
    file_size = Column(BigInteger, nullable=False)  # Size in bytes

    # Relationships
    message_id = Column(Integer, ForeignKey("internal_chat_messages.id"), nullable=False)
    uploaded_by = Column(Integer, ForeignKey("users.id"), nullable=False)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    message = relationship("InternalChatMessage", back_populates="attachments")
    uploader = relationship("User")
