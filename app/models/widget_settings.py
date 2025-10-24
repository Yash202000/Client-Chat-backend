
from sqlalchemy import Boolean, Column, Integer, String, ForeignKey, JSON
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
    agent_avatar_url = Column(String, nullable=True)
    input_placeholder = Column(String, default="Type a message...")
    user_message_color = Column(String, default="#3B82F6")
    user_message_text_color = Column(String, default="#FFFFFF")
    bot_message_color = Column(String, default="#E0E7FF")
    bot_message_text_color = Column(String, default="#1F2937")
    time_color = Column(String, default="#9CA3AF")
    widget_size = Column(String, default="medium")
    show_header = Column(Boolean, default=True)
    livekit_url = Column(String, nullable=True)
    frontend_url = Column(String, nullable=True)
    proactive_message_enabled = Column(Boolean, default=False)
    proactive_message = Column(String, default="Hello! Do you have any questions?")
    proactive_message_delay = Column(Integer, default=5)
    suggestions_enabled = Column(Boolean, default=False)
    dark_mode = Column(Boolean, default=False)
    typing_indicator_enabled = Column(Boolean, default=False)
    communication_mode = Column(String, default="chat")
    meta = Column(JSON, nullable=True, default={})  # Flexible JSON field for additional customizations
    agent_id = Column(Integer, ForeignKey("agents.id"))

    agent = relationship("Agent", back_populates="widget_settings")
