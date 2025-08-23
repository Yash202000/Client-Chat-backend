
from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, func, JSON
from sqlalchemy.orm import relationship
from app.core.database import Base

class VideoCall(Base):
    __tablename__ = "video_calls"

    id = Column(Integer, primary_key=True, index=True)
    room_name = Column(String, unique=True, index=True, nullable=False)
    status = Column(String, default="initiated") # initiated, active, completed
    
    channel_id = Column(Integer, ForeignKey("chat_channels.id"), nullable=False)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    participants = Column(JSON, nullable=True) # Store list of user IDs
    
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    ended_at = Column(DateTime(timezone=True), nullable=True)

    channel = relationship("ChatChannel")
    creator = relationship("User")
