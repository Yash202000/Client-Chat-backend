from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Enum, DECIMAL
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from datetime import datetime
import enum
from app.core.database import Base


class ActivityType(str, enum.Enum):
    """Campaign activity event types"""
    # Email activities
    EMAIL_SENT = "email_sent"
    EMAIL_DELIVERED = "email_delivered"
    EMAIL_OPENED = "email_opened"
    EMAIL_CLICKED = "email_clicked"
    EMAIL_REPLIED = "email_replied"
    EMAIL_BOUNCED = "email_bounced"
    EMAIL_UNSUBSCRIBED = "email_unsubscribed"

    # SMS activities
    SMS_SENT = "sms_sent"
    SMS_DELIVERED = "sms_delivered"
    SMS_REPLIED = "sms_replied"
    SMS_FAILED = "sms_failed"

    # WhatsApp activities
    WHATSAPP_SENT = "whatsapp_sent"
    WHATSAPP_DELIVERED = "whatsapp_delivered"
    WHATSAPP_READ = "whatsapp_read"
    WHATSAPP_REPLIED = "whatsapp_replied"

    # Voice call activities
    CALL_INITIATED = "call_initiated"
    CALL_RINGING = "call_ringing"
    CALL_ANSWERED = "call_answered"
    CALL_COMPLETED = "call_completed"
    CALL_FAILED = "call_failed"
    CALL_BUSY = "call_busy"
    CALL_NO_ANSWER = "call_no_answer"
    VOICEMAIL_DETECTED = "voicemail_detected"
    VOICEMAIL_LEFT = "voicemail_left"

    # Conversation activities
    CONVERSATION_STARTED = "conversation_started"
    CONVERSATION_REPLIED = "conversation_replied"
    CONVERSATION_ENDED = "conversation_ended"

    # Conversion activities
    FORM_SUBMITTED = "form_submitted"
    MEETING_BOOKED = "meeting_booked"
    LEAD_QUALIFIED = "lead_qualified"
    OPPORTUNITY_CREATED = "opportunity_created"
    DEAL_WON = "deal_won"
    DEAL_LOST = "deal_lost"

    # Engagement activities
    LINK_CLICKED = "link_clicked"
    CONTENT_VIEWED = "content_viewed"
    DOCUMENT_DOWNLOADED = "document_downloaded"

    # Other
    OPTED_OUT = "opted_out"
    ERROR = "error"


class CampaignActivity(Base):
    __tablename__ = "campaign_activities"

    # Primary fields
    id = Column(Integer, primary_key=True, index=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), nullable=False, index=True)
    contact_id = Column(Integer, ForeignKey("contacts.id"), nullable=False, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id"), nullable=True, index=True)
    message_id = Column(Integer, ForeignKey("campaign_messages.id"), nullable=True, index=True)

    # Activity details
    activity_type = Column(Enum(ActivityType), nullable=False, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    # Activity data (flexible JSON storage)
    activity_data = Column(JSONB, nullable=True)
    # Examples by activity type:
    # EMAIL_OPENED: {"ip_address": "1.2.3.4", "user_agent": "...", "location": "San Francisco, CA"}
    # LINK_CLICKED: {"url": "https://example.com/product", "link_text": "Learn More"}
    # CALL_COMPLETED: {"duration": 120, "recording_url": "https://...", "transcript": "..."}
    # DEAL_WON: {"deal_value": 5000, "close_date": "2024-01-15"}

    # Revenue attribution (for conversion events)
    revenue_amount = Column(DECIMAL(10, 2), nullable=True)

    # External IDs (for tracking across systems)
    external_id = Column(String, nullable=True, index=True)  # e.g., Twilio call SID, email message ID
    session_id = Column(String, nullable=True, index=True)  # Related conversation session

    # Error tracking
    error_message = Column(String, nullable=True)
    error_code = Column(String, nullable=True)

    # Relationships
    campaign = relationship("Campaign", back_populates="activities")
    contact = relationship("Contact", back_populates="campaign_activities")
    lead = relationship("Lead", back_populates="activities")
    message = relationship("CampaignMessage", back_populates="activities")


# Add back-population to Contact model
from app.models.contact import Contact

Contact.campaign_activities = relationship("CampaignActivity", order_by=CampaignActivity.timestamp.desc(), back_populates="contact")
