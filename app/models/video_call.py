
from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, func, JSON, Boolean
from sqlalchemy.orm import relationship
from app.core.database import Base

class VideoCall(Base):
    __tablename__ = "video_calls"

    id = Column(Integer, primary_key=True, index=True)
    room_name = Column(String, unique=True, index=True, nullable=False)
    status = Column(String, default="ringing") # ringing, active, completed, missed, rejected, cancelled

    channel_id = Column(Integer, ForeignKey("chat_channels.id"), nullable=False)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    # Track who was invited vs who joined
    invited_users = Column(JSON, nullable=True) # List of user IDs who were invited
    joined_users = Column(JSON, nullable=True) # List of user IDs who joined

    # Call timing
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    answered_at = Column(DateTime(timezone=True), nullable=True) # When first person joined
    ended_at = Column(DateTime(timezone=True), nullable=True)

    # Call timeout (30 seconds default)
    timeout_seconds = Column(Integer, default=30)

    # Legacy field for backwards compatibility
    participants = Column(JSON, nullable=True)

    channel = relationship("ChatChannel")
    creator = relationship("User")
