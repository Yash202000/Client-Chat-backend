from sqlalchemy import Column, Integer, String, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from app.core.database import Base


class WhatsAppWidget(Base):
    __tablename__ = "whatsapp_widgets"

    id = Column(Integer, primary_key=True, index=True)
    widget_key = Column(String(64), unique=True, index=True, nullable=False)  # public ID for embed
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)

    # Display config
    name = Column(String(255), nullable=False, default="WhatsApp Widget")  # internal label
    phone_number = Column(String(30), nullable=False)         # E.164 or local, e.g. 919876543210
    prefill_message = Column(String(500), nullable=True)      # pre-filled text in WA
    greeting_text = Column(String(255), default="Chat with us on WhatsApp!")
    subtext = Column(String(255), default="Typically replies within minutes")
    button_label = Column(String(100), default="Chat on WhatsApp")

    # Style
    button_color = Column(String(20), default="#25D366")      # WhatsApp green
    button_text_color = Column(String(20), default="#FFFFFF")
    position = Column(String(20), default="bottom-right")     # bottom-right | bottom-left
    show_tooltip = Column(Boolean, default=True)
    show_agent_avatar = Column(Boolean, default=False)
    agent_avatar_url = Column(String(500), nullable=True)
    agent_name = Column(String(100), nullable=True)

    is_active = Column(Boolean, default=True)

    company = relationship("Company", foreign_keys=[company_id])
