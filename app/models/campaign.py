from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Enum, DECIMAL, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from datetime import datetime
import enum
from app.core.database import Base


class CampaignType(str, enum.Enum):
    """Campaign channel types"""
    EMAIL = "email"
    SMS = "sms"
    WHATSAPP = "whatsapp"
    VOICE = "voice"  # Twilio voice calls
    MULTI_CHANNEL = "multi_channel"  # Combination of channels


class CampaignStatus(str, enum.Enum):
    """Campaign lifecycle status"""
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class GoalType(str, enum.Enum):
    """Campaign goal types"""
    LEAD_GENERATION = "lead_generation"
    NURTURE = "nurture"
    CONVERSION = "conversion"
    ENGAGEMENT = "engagement"
    RETENTION = "retention"
    REACTIVATION = "reactivation"


class Campaign(Base):
    __tablename__ = "campaigns"

    # Primary fields
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, index=True)
    description = Column(Text, nullable=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)

    # Campaign type and channel
    campaign_type = Column(Enum(CampaignType), nullable=False, index=True)
    status = Column(Enum(CampaignStatus), default=CampaignStatus.DRAFT, nullable=False, index=True)

    # Integration with existing AgentConnect features
    workflow_id = Column(Integer, ForeignKey("workflows.id"), nullable=True)  # Automated sequence workflow
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=True)  # AI agent for conversational campaigns

    # Ownership and assignment
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    owner_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    # Scheduling
    start_date = Column(DateTime, nullable=True)
    end_date = Column(DateTime, nullable=True)
    scheduled_send_time = Column(DateTime, nullable=True)

    # Targeting
    target_criteria = Column(JSONB, nullable=True)  # Filters for contact selection
    # Example: {"lead_stage": ["lead", "mql"], "tags": ["interested"], "score_min": 50}

    # Goals and budget
    goal_type = Column(Enum(GoalType), nullable=True)
    goal_value = Column(Integer, nullable=True)  # e.g., number of conversions
    budget = Column(DECIMAL(10, 2), nullable=True)
    actual_cost = Column(DECIMAL(10, 2), default=0, nullable=True)

    # Campaign settings
    settings = Column(JSONB, nullable=True)
    # Example: {
    #   "send_time_optimization": true,
    #   "ab_testing_enabled": false,
    #   "unsubscribe_link": true,
    #   "track_opens": true,
    #   "track_clicks": true
    # }

    # Voice campaign specific (Twilio)
    twilio_config = Column(JSONB, nullable=True)
    # Example: {
    #   "from_number": "+1234567890",
    #   "caller_id": "My Company",
    #   "max_call_duration": 300,
    #   "voicemail_detection": true,
    #   "record_calls": true
    # }

    # Metrics (cached for performance)
    total_contacts = Column(Integer, default=0, nullable=False)
    contacts_reached = Column(Integer, default=0, nullable=False)
    contacts_engaged = Column(Integer, default=0, nullable=False)
    contacts_converted = Column(Integer, default=0, nullable=False)
    total_revenue = Column(DECIMAL(10, 2), default=0, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    last_run_at = Column(DateTime, nullable=True)

    # Relationships
    company = relationship("Company", back_populates="campaigns")
    workflow = relationship("Workflow", back_populates="campaigns")
    agent = relationship("Agent", back_populates="campaigns")
    created_by = relationship("User", foreign_keys=[created_by_user_id], back_populates="created_campaigns")
    owner = relationship("User", foreign_keys=[owner_user_id], back_populates="owned_campaigns")

    # Related entities
    messages = relationship("CampaignMessage", back_populates="campaign", cascade="all, delete-orphan", order_by="CampaignMessage.sequence_order")
    campaign_contacts = relationship("CampaignContact", back_populates="campaign", cascade="all, delete-orphan")
    activities = relationship("CampaignActivity", back_populates="campaign", cascade="all, delete-orphan")
    leads = relationship("Lead", back_populates="campaign")


# Add back-population to related models
from app.models.company import Company
from app.models.user import User

Company.campaigns = relationship("Campaign", order_by=Campaign.id, back_populates="company")
User.created_campaigns = relationship("Campaign", foreign_keys=[Campaign.created_by_user_id], back_populates="created_by")
User.owned_campaigns = relationship("Campaign", foreign_keys=[Campaign.owner_user_id], back_populates="owner")
