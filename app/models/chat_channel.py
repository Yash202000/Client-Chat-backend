
from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, func, Enum
from sqlalchemy.orm import relationship
from app.core.database import Base
import enum

class ChannelType(enum.Enum):
    TEAM = "team"
    DM = "dm"

class ChatChannel(Base):
    __tablename__ = "chat_channels"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=True) # Nullable for DM channels
    description = Column(String, nullable=True)
    channel_type = Column(Enum(ChannelType, values_callable=lambda x: [e.name for e in x]), nullable=False, default=ChannelType.TEAM)
    
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=True) # Nullable for DM channels
    creator_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    company = relationship("Company")
    team = relationship("Team")
    creator = relationship("User")
    
    participants = relationship("ChannelMembership", back_populates="channel", cascade="all, delete-orphan")
    messages = relationship("InternalChatMessage", back_populates="channel", cascade="all, delete-orphan")
