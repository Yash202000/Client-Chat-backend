from sqlalchemy import Column, Integer, String, JSON, ForeignKey, Boolean, DateTime, Enum
from sqlalchemy.orm import relationship
from datetime import datetime
import enum
from app.core.database import Base


class LifecycleStage(str, enum.Enum):
    """Contact lifecycle stages"""
    SUBSCRIBER = "subscriber"  # Newsletter/content subscriber
    LEAD = "lead"  # Potential customer
    MQL = "mql"  # Marketing qualified lead
    SQL = "sql"  # Sales qualified lead
    OPPORTUNITY = "opportunity"  # Active sales opportunity
    CUSTOMER = "customer"  # Paying customer
    EVANGELIST = "evangelist"  # Brand advocate/promoter
    OTHER = "other"


class OptInStatus(str, enum.Enum):
    """Contact communication opt-in status"""
    OPTED_IN = "opted_in"
    OPTED_OUT = "opted_out"
    PENDING = "pending"
    UNKNOWN = "unknown"


class Contact(Base):
    __tablename__ = "contacts"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=True)
    name = Column(String, index=True, nullable=True)
    phone_number = Column(String, nullable=True)
    custom_attributes = Column(JSON, nullable=True)

    # CRM fields
    lead_source = Column(String, nullable=True, index=True)  # e.g., "website", "referral", "campaign_123"
    lifecycle_stage = Column(Enum(LifecycleStage), default=LifecycleStage.LEAD, nullable=True, index=True)

    # Communication preferences
    do_not_contact = Column(Boolean, default=False, nullable=False)
    opt_in_status = Column(Enum(OptInStatus), default=OptInStatus.UNKNOWN, nullable=False)
    opt_in_date = Column(DateTime, nullable=True)
    opt_out_date = Column(DateTime, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=True)
    last_contacted_at = Column(DateTime, nullable=True)

    company_id = Column(Integer, ForeignKey("companies.id"))
    company = relationship("Company", back_populates="contacts")

    chat_messages = relationship("ChatMessage", back_populates="contact")
    sessions = relationship("ConversationSession", back_populates="contact")

# Add back-population to Company model
from app.models.company import Company
Company.contacts = relationship("Contact", order_by=Contact.id, back_populates="company")
