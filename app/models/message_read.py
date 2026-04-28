from sqlalchemy import Column, Integer, ForeignKey, DateTime, func, UniqueConstraint
from sqlalchemy.orm import relationship
from app.core.database import Base


class MessageRead(Base):
    __tablename__ = "message_reads"
    __table_args__ = (UniqueConstraint('message_id', 'user_id', name='uq_message_read'),)

    id = Column(Integer, primary_key=True, index=True)
    message_id = Column(Integer, ForeignKey("internal_chat_messages.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    read_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User")
