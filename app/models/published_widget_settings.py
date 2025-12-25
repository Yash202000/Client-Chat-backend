import uuid
from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, JSON, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from app.core.database import Base


class PublishedWidgetSettings(Base):
    __tablename__ = "published_widget_settings"

    id = Column(Integer, primary_key=True, index=True)
    publish_id = Column(String, unique=True, index=True, default=lambda: str(uuid.uuid4()))
    agent_id = Column(Integer, ForeignKey("agents.id"), unique=True, index=True, nullable=True)
    settings = Column(JSON)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationship to agent
    agent = relationship("Agent", back_populates="published_settings")
