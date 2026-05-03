import uuid
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Enum, Text
from sqlalchemy.orm import relationship
from datetime import datetime
import enum
from app.core.database import Base


class TrackingTokenType(str, enum.Enum):
    OPEN = "open"
    CLICK = "click"


class EmailTrackingToken(Base):
    """
    Tracks opens and clicks for outbound 1:1 sales emails.
    One open-token per email, one click-token per tracked link.
    """
    __tablename__ = "email_tracking_tokens"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    token = Column(String(36), unique=True, index=True, nullable=False, default=lambda: str(uuid.uuid4()))
    token_type = Column(Enum(TrackingTokenType), nullable=False, index=True)

    # What entity this email was sent to/for
    contact_id = Column(Integer, ForeignKey("contacts.id"), nullable=True, index=True)
    deal_id = Column(Integer, ForeignKey("deals.id"), nullable=True, index=True)

    # Campaign linkage (null for 1:1 sales emails)
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), nullable=True, index=True)
    campaign_message_id = Column(Integer, ForeignKey("campaign_messages.id"), nullable=True, index=True)

    # For click tokens: the destination URL
    original_url = Column(Text, nullable=True)

    # Email metadata
    email_subject = Column(String, nullable=True)
    sent_by = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    # Firing data (set on first fire)
    first_fired_at = Column(DateTime, nullable=True)
    last_fired_at = Column(DateTime, nullable=True)
    fire_count = Column(Integer, default=0, nullable=False)
    last_ip = Column(String, nullable=True)
    last_user_agent = Column(String, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    contact = relationship("Contact")
    sender = relationship("User", foreign_keys=[sent_by])
