from sqlalchemy import Column, Integer, String, JSON, ForeignKey, Boolean, DateTime, Enum, Text
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
    lead_source = Column(String, nullable=True, index=True)
    # Workflow-driven lifecycle stage (new) — replaces hardcoded LifecycleStage enum
    workflow_id = Column(Integer, ForeignKey("ticket_workflows.id"), nullable=True, index=True)
    status_id = Column(Integer, ForeignKey("ticket_statuses.id"), nullable=True, index=True)
    # Keep lifecycle_stage as nullable for backward compat
    lifecycle_stage = Column(Enum(LifecycleStage), nullable=True, index=True)

    # Communication preferences
    do_not_contact = Column(Boolean, default=False, nullable=False)
    opt_in_status = Column(Enum(OptInStatus), default=OptInStatus.UNKNOWN, nullable=False)
    opt_in_date = Column(DateTime, nullable=True)
    opt_out_date = Column(DateTime, nullable=True)

    # Profile picture (fetched from channel, e.g. WhatsApp)
    profile_picture_url = Column(String, nullable=True)

    # Social profile fields
    linkedin_url = Column(String, nullable=True, index=True)
    linkedin_urn = Column(String, nullable=True)          # LinkedIn member URN for API calls
    instagram_handle = Column(String, nullable=True)
    facebook_url = Column(String, nullable=True)
    job_title = Column(String, nullable=True, index=True)
    company_name = Column(String, nullable=True, index=True)  # denormalized for import
    industry = Column(String, nullable=True, index=True)
    location = Column(String, nullable=True)
    website = Column(String, nullable=True)
    enriched_at = Column(DateTime, nullable=True)             # when enrichment last ran
    enrichment_source = Column(String, nullable=True)         # "linkedin_api" | "ai_knowledge" | "manual"

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=True)
    last_contacted_at = Column(DateTime, nullable=True)

    company_id = Column(Integer, ForeignKey("companies.id"))
    company = relationship("Company", back_populates="contacts")
    workflow = relationship("TicketWorkflow", foreign_keys=[workflow_id])
    status = relationship("TicketStatus", foreign_keys=[status_id])

    # CRM B2B account link (nullable — not all contacts belong to an account)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True, index=True)
    account = relationship("Account", back_populates="contacts")

    chat_messages = relationship("ChatMessage", back_populates="contact")
    sessions = relationship("ConversationSession", back_populates="contact")

# Add back-population to Company model
from app.models.company import Company
Company.contacts = relationship("Contact", order_by=Contact.id, back_populates="company")
