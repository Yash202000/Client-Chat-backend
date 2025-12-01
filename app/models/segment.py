from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Enum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from datetime import datetime
import enum
from app.core.database import Base


class SegmentType(str, enum.Enum):
    """Segment type"""
    DYNAMIC = "dynamic"  # Filter-based, auto-updates
    STATIC = "static"  # Manual selection, fixed list


class Segment(Base):
    """Segment model for grouping leads and contacts"""
    __tablename__ = "segments"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, index=True)
    description = Column(Text, nullable=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)

    # Segment type
    segment_type = Column(Enum(SegmentType), default=SegmentType.DYNAMIC, nullable=False)

    # Filter criteria for dynamic segments
    # Example: {
    #   "lifecycle_stages": ["lead", "mql"],
    #   "lead_sources": ["website", "referral"],
    #   "lead_stages": ["lead", "mql"],
    #   "tag_ids": [1, 2, 3],
    #   "score_min": 50,
    #   "score_max": 100,
    #   "opt_in_status": ["opted_in"],
    #   "include_contacts": true,
    #   "include_leads": true
    # }
    criteria = Column(JSONB, nullable=True)

    # Static member lists (for static segments)
    static_contact_ids = Column(JSONB, nullable=True)  # [1, 2, 3...]
    static_lead_ids = Column(JSONB, nullable=True)  # [1, 2, 3...]

    # Cached counts (updated on refresh)
    contact_count = Column(Integer, default=0, nullable=False)
    lead_count = Column(Integer, default=0, nullable=False)
    last_refreshed_at = Column(DateTime, nullable=True)

    # Ownership
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    company = relationship("Company", back_populates="segments")
    created_by = relationship("User", back_populates="created_segments")
    campaigns = relationship("Campaign", back_populates="segment")


# Add relationships to Company, User, and Campaign models
from app.models.company import Company
from app.models.user import User
from app.models.campaign import Campaign

Company.segments = relationship("Segment", order_by=Segment.name, back_populates="company")
User.created_segments = relationship("Segment", back_populates="created_by")
Campaign.segment = relationship("Segment", back_populates="campaigns")
