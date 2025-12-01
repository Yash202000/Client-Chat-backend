from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Enum, DECIMAL
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from datetime import datetime
import enum
from app.core.database import Base


class LeadStage(str, enum.Enum):
    """Standard B2B sales pipeline stages"""
    LEAD = "lead"  # Initial lead
    MQL = "mql"  # Marketing Qualified Lead
    SQL = "sql"  # Sales Qualified Lead
    OPPORTUNITY = "opportunity"  # Active opportunity
    CUSTOMER = "customer"  # Won/converted
    LOST = "lost"  # Lost opportunity


class QualificationStatus(str, enum.Enum):
    """Lead qualification status"""
    UNQUALIFIED = "unqualified"
    IN_PROGRESS = "in_progress"
    QUALIFIED = "qualified"
    DISQUALIFIED = "disqualified"


class Lead(Base):
    __tablename__ = "leads"

    # Primary fields
    id = Column(Integer, primary_key=True, index=True)
    contact_id = Column(Integer, ForeignKey("contacts.id"), nullable=False, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)

    # Assignment and source
    assignee_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    source = Column(String, nullable=True, index=True)  # e.g., "website", "campaign", "referral", "import"
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), nullable=True, index=True)

    # Pipeline stage
    stage = Column(Enum(LeadStage), default=LeadStage.LEAD, nullable=False, index=True)
    stage_changed_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    previous_stage = Column(Enum(LeadStage), nullable=True)

    # Qualification
    qualification_status = Column(Enum(QualificationStatus), default=QualificationStatus.UNQUALIFIED, nullable=False)
    qualification_data = Column(JSONB, nullable=True)  # Stores answers to qualification questions

    # Scoring (0-100)
    score = Column(Integer, default=0, nullable=False, index=True)
    last_scored_at = Column(DateTime, nullable=True)

    # Deal/Revenue tracking
    deal_value = Column(DECIMAL(10, 2), nullable=True)  # Estimated or actual deal value
    expected_close_date = Column(DateTime, nullable=True)
    actual_close_date = Column(DateTime, nullable=True)
    won_reason = Column(String, nullable=True)
    lost_reason = Column(String, nullable=True)

    # Additional metadata
    notes = Column(String, nullable=True)
    tags = Column(JSONB, nullable=True)  # Array of tags
    custom_fields = Column(JSONB, nullable=True)  # Flexible custom data

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    contact = relationship("Contact", back_populates="leads")
    company = relationship("Company", back_populates="leads")
    assignee = relationship("User", foreign_keys=[assignee_id], back_populates="assigned_leads")
    campaign = relationship("Campaign", back_populates="leads")

    # Related entities
    scores = relationship("LeadScore", back_populates="lead", cascade="all, delete-orphan")
    campaign_contacts = relationship("CampaignContact", back_populates="lead")
    activities = relationship("CampaignActivity", back_populates="lead")


# Add back-population to related models
from app.models.contact import Contact
from app.models.company import Company
from app.models.user import User

Contact.leads = relationship("Lead", order_by=Lead.id, back_populates="contact")
Company.leads = relationship("Lead", order_by=Lead.id, back_populates="company")
User.assigned_leads = relationship("Lead", foreign_keys=[Lead.assignee_id], back_populates="assignee")
