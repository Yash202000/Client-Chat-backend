import enum
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey, Enum
from sqlalchemy.dialects.postgresql import JSONB, ARRAY
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


class TemplateType(enum.Enum):
    EMAIL = "email"
    SMS = "sms"
    WHATSAPP = "whatsapp"
    VOICE = "voice"


class Template(Base):
    """
    Reusable message templates for campaigns.
    Supports email, SMS, WhatsApp, and voice channels.
    """
    __tablename__ = "templates"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    # Basic info
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    template_type = Column(Enum(TemplateType), nullable=False, index=True)

    # Email fields
    subject = Column(String(500), nullable=True)
    body = Column(Text, nullable=True)  # Plain text body
    html_body = Column(Text, nullable=True)  # HTML body for email

    # Voice fields
    voice_script = Column(Text, nullable=True)
    tts_voice_id = Column(String(100), nullable=True)

    # WhatsApp fields
    whatsapp_template_name = Column(String(255), nullable=True)
    whatsapp_template_params = Column(JSONB, nullable=True)

    # Metadata
    personalization_tokens = Column(ARRAY(String(100)), nullable=True, default=[])
    tags = Column(ARRAY(String(50)), nullable=True, default=[])
    is_ai_generated = Column(Boolean, default=False)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    company = relationship("Company", backref="templates")
    created_by = relationship("User", backref="created_templates")

    def __repr__(self):
        return f"<Template(id={self.id}, name='{self.name}', type={self.template_type.value})>"
