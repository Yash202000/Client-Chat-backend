from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Enum, Text, Boolean
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from datetime import datetime
import enum
from app.core.database import Base


class MessageType(str, enum.Enum):
    """Message delivery channel types"""
    EMAIL = "email"
    SMS = "sms"
    WHATSAPP = "whatsapp"
    INSTAGRAM = "instagram"
    TELEGRAM = "telegram"
    VOICE = "voice"  # Twilio voice call
    AI_CONVERSATION = "ai_conversation"  # AI agent initiates conversation


class DelayUnit(str, enum.Enum):
    """Time units for message delays"""
    MINUTES = "minutes"
    HOURS = "hours"
    DAYS = "days"
    WEEKS = "weeks"


class CampaignMessage(Base):
    __tablename__ = "campaign_messages"

    # Primary fields
    id = Column(Integer, primary_key=True, index=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), nullable=False, index=True)

    # Sequence
    sequence_order = Column(Integer, nullable=False)  # Order in the campaign sequence (1, 2, 3, ...)
    name = Column(String, nullable=True)  # Internal name for the message step

    # Message type
    message_type = Column(Enum(MessageType), nullable=False)

    # Template reference (optional - can use template or inline content)
    template_id = Column(Integer, ForeignKey("templates.id"), nullable=True)

    # Email content
    subject = Column(String, nullable=True)  # For email messages
    body = Column(Text, nullable=True)  # Email/SMS text content
    html_body = Column(Text, nullable=True)  # HTML email content

    # Voice content (Twilio)
    voice_script = Column(Text, nullable=True)  # Script for AI voice agent or TTS
    tts_voice_id = Column(String, nullable=True)  # Text-to-speech voice ID
    voice_agent_id = Column(Integer, ForeignKey("agents.id"), nullable=True)  # AI agent for voice calls

    # Twilio voice configuration
    twilio_phone_number = Column(String, nullable=True)  # From phone number
    call_flow_config = Column(JSONB, nullable=True)
    # Example: {
    #   "intro_message": "Hello, this is...",
    #   "gather_input": true,
    #   "max_retries": 3,
    #   "transfer_to": "+1234567890",
    #   "voicemail_message": "Please call us back at...",
    #   "record_call": true
    # }

    # WhatsApp template
    whatsapp_template_name = Column(String, nullable=True)
    whatsapp_template_params = Column(JSONB, nullable=True)

    # Timing and delays
    delay_amount = Column(Integer, default=0, nullable=False)  # Delay before sending this message
    delay_unit = Column(Enum(DelayUnit), default=DelayUnit.DAYS, nullable=False)

    # Send time optimization
    send_time_window_start = Column(String, nullable=True)  # e.g., "09:00" (HH:MM format)
    send_time_window_end = Column(String, nullable=True)  # e.g., "17:00"
    send_on_weekdays_only = Column(Boolean, default=False, nullable=False)

    # A/B Testing
    is_ab_test = Column(Boolean, default=False, nullable=False)
    ab_variant = Column(String, nullable=True)  # e.g., "A", "B"
    ab_split_percentage = Column(Integer, nullable=True)  # Percentage of contacts receiving this variant

    # Personalization
    personalization_tokens = Column(JSONB, nullable=True)
    # Example: ["{{first_name}}", "{{company_name}}", "{{deal_value}}"]

    # Call-to-action tracking
    cta_text = Column(String, nullable=True)
    cta_url = Column(String, nullable=True)
    track_clicks = Column(Boolean, default=True, nullable=False)

    # Conditions for sending
    send_conditions = Column(JSONB, nullable=True)
    # Example: {"lead_score_min": 50, "previous_message_opened": true}

    # Status
    is_active = Column(Boolean, default=True, nullable=False)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    campaign = relationship("Campaign", back_populates="messages")
    template = relationship("Template", foreign_keys=[template_id])
    voice_agent = relationship("Agent", foreign_keys=[voice_agent_id])
    activities = relationship("CampaignActivity", back_populates="message", cascade="all, delete-orphan")
