
from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.orm import relationship
from app.core.database import Base

class WidgetSettings(Base):
    __tablename__ = "widget_settings"

    id = Column(Integer, primary_key=True, index=True)
    primary_color = Column(String, default="#3B82F6")
    header_title = Column(String, default="Customer Support")
    welcome_message = Column(String, default="Hi! How can I help you today?")
    position = Column(String, default="bottom-right")
    border_radius = Column(Integer, default=12)
    font_family = Column(String, default="Inter")
    agent_id = Column(Integer, ForeignKey("agents.id"))

    agent = relationship("Agent", back_populates="widget_settings")
