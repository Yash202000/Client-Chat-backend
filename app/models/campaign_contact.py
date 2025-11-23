from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Enum, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from datetime import datetime
import enum
from app.core.database import Base


class EnrollmentStatus(str, enum.Enum):
    """Campaign enrollment status"""
    PENDING = "pending"  # Enrolled but not started
    ACTIVE = "active"  # Currently receiving messages
    COMPLETED = "completed"  # Finished the campaign sequence
    OPTED_OUT = "opted_out"  # Unsubscribed from campaign
    BOUNCED = "bounced"  # Email/SMS bounced
    FAILED = "failed"  # Campaign delivery failed
    PAUSED = "paused"  # Temporarily paused


class CampaignContact(Base):
    __tablename__ = "campaign_contacts"
    __table_args__ = (
        UniqueConstraint('campaign_id', 'contact_id', name='uq_campaign_contact'),
    )

    # Primary fields
    id = Column(Integer, primary_key=True, index=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), nullable=False, index=True)
    contact_id = Column(Integer, ForeignKey("contacts.id"), nullable=False, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id"), nullable=True, index=True)

    # Enrollment
    enrolled_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    enrolled_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    status = Column(Enum(EnrollmentStatus), default=EnrollmentStatus.PENDING, nullable=False, index=True)

    # Progress tracking
    current_step = Column(Integer, default=0, nullable=False)  # Which message in the sequence
    current_message_id = Column(Integer, ForeignKey("campaign_messages.id"), nullable=True)
    next_scheduled_at = Column(DateTime, nullable=True)  # When next message should be sent

    # Engagement tracking
    last_interaction_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    opted_out_at = Column(DateTime, nullable=True)
    opt_out_reason = Column(String, nullable=True)

    # Metrics (aggregated from activities)
    opens = Column(Integer, default=0, nullable=False)
    clicks = Column(Integer, default=0, nullable=False)
    replies = Column(Integer, default=0, nullable=False)
    conversions = Column(Integer, default=0, nullable=False)

    # Voice campaign specific
    calls_initiated = Column(Integer, default=0, nullable=False)
    calls_completed = Column(Integer, default=0, nullable=False)
    total_call_duration = Column(Integer, default=0, nullable=False)  # in seconds
    voicemails_left = Column(Integer, default=0, nullable=False)

    # Custom data and metadata
    enrollment_data = Column(JSONB, nullable=True)  # Data captured at enrollment
    # Example: {"utm_source": "facebook", "original_url": "example.com/signup"}

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    campaign = relationship("Campaign", back_populates="campaign_contacts")
    contact = relationship("Contact", back_populates="campaign_enrollments")
    lead = relationship("Lead", back_populates="campaign_contacts")
    enrolled_by = relationship("User", foreign_keys=[enrolled_by_user_id])
    current_message = relationship("CampaignMessage", foreign_keys=[current_message_id])


# Add back-population to related models
from app.models.contact import Contact
from app.models.user import User

Contact.campaign_enrollments = relationship("CampaignContact", order_by=CampaignContact.id, back_populates="contact")
