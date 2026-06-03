from sqlalchemy import Column, Integer, String, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from app.core.database import Base


class SocialWidget(Base):
    __tablename__ = "social_widgets"

    id = Column(Integer, primary_key=True, index=True)
    widget_key = Column(String(64), unique=True, index=True, nullable=False)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)

    channel = Column(String(20), nullable=False)   # 'instagram' | 'telegram' | 'messenger'
    name = Column(String(255), nullable=False, default="Widget")
    handle = Column(String(255), nullable=False)   # IG username / TG bot username / FB page username

    greeting_text = Column(String(255), default="Chat with us!")
    subtext = Column(String(255), default="Typically replies within minutes")
    button_label = Column(String(100), default="Chat now")

    button_color = Column(String(20), default="#000000")
    button_text_color = Column(String(20), default="#FFFFFF")
    position = Column(String(20), default="bottom-right")
    show_tooltip = Column(Boolean, default=True)
    show_agent_avatar = Column(Boolean, default=False)
    agent_avatar_url = Column(String(500), nullable=True)
    agent_name = Column(String(100), nullable=True)

    is_active = Column(Boolean, default=True)

    company = relationship("Company", foreign_keys=[company_id])
