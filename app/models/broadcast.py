from sqlalchemy import Column, Integer, String, Text, DateTime, Enum, ForeignKey, Boolean
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from datetime import datetime
import enum
from app.core.database import Base


class BroadcastChannel(str, enum.Enum):
    WHATSAPP = "whatsapp"
    SMS = "sms"
    EMAIL = "email"


class BroadcastStatus(str, enum.Enum):
    DRAFT = "draft"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SCHEDULED = "scheduled"


class BroadcastContactStatus(str, enum.Enum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    SKIPPED = "skipped"   # no phone number


class Broadcast(Base):
    __tablename__ = "broadcasts"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    channel = Column(Enum(BroadcastChannel), nullable=False)
    subject = Column(String(500), nullable=True)  # email subject line
    message = Column(Text, nullable=False)

    # Target
    segment_id = Column(Integer, ForeignKey("segments.id"), nullable=True)
    # If segment_id is null, all contacts with phone numbers are targeted

    # Stats
    total_contacts = Column(Integer, default=0)
    sent_count = Column(Integer, default=0)
    failed_count = Column(Integer, default=0)
    skipped_count = Column(Integer, default=0)

    status = Column(Enum(BroadcastStatus), default=BroadcastStatus.DRAFT, nullable=False)
    scheduled_at = Column(DateTime, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    company = relationship("Company", foreign_keys=[company_id])
    segment = relationship("Segment", foreign_keys=[segment_id])
    contacts = relationship("BroadcastContact", back_populates="broadcast", cascade="all, delete-orphan")


class BroadcastContact(Base):
    __tablename__ = "broadcast_contacts"

    id = Column(Integer, primary_key=True, index=True)
    broadcast_id = Column(Integer, ForeignKey("broadcasts.id", ondelete="CASCADE"), nullable=False, index=True)
    contact_id = Column(Integer, ForeignKey("contacts.id"), nullable=False)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)

    status = Column(Enum(BroadcastContactStatus), default=BroadcastContactStatus.PENDING, nullable=False)
    error_message = Column(Text, nullable=True)
    sent_at = Column(DateTime, nullable=True)

    broadcast = relationship("Broadcast", back_populates="contacts")
    contact = relationship("Contact", foreign_keys=[contact_id])
