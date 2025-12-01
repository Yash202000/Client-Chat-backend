from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Enum, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from datetime import datetime
import enum
from app.core.database import Base


class ScoreType(str, enum.Enum):
    """Types of lead scoring"""
    AI_INTENT = "ai_intent"  # AI-detected purchase intent from conversations
    ENGAGEMENT = "engagement"  # Based on email opens, clicks, replies, etc.
    DEMOGRAPHIC = "demographic"  # Based on company size, industry, role, etc.
    BEHAVIORAL = "behavioral"  # Based on website visits, content downloads, etc.
    WORKFLOW = "workflow"  # Score from completing workflow qualification steps
    MANUAL = "manual"  # Manually set by sales rep
    COMBINED = "combined"  # Weighted combination of multiple scores


class LeadScore(Base):
    __tablename__ = "lead_scores"

    # Primary fields
    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id"), nullable=False, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)

    # Score details
    score_type = Column(Enum(ScoreType), nullable=False, index=True)
    score_value = Column(Integer, nullable=False)  # 0-100 scale
    weight = Column(Float, default=1.0, nullable=False)  # Weight for combined scoring

    # Reasoning and context
    score_reason = Column(Text, nullable=True)  # Human-readable explanation
    score_factors = Column(JSONB, nullable=True)  # Detailed breakdown
    # Example for AI_INTENT: {
    #   "intent": "purchase",
    #   "confidence": 0.87,
    #   "keywords": ["pricing", "enterprise plan", "demo"],
    #   "conversation_id": "abc123"
    # }
    # Example for ENGAGEMENT: {
    #   "email_opens": 5,
    #   "link_clicks": 3,
    #   "reply_count": 2,
    #   "last_interaction": "2024-01-15"
    # }

    # AI-specific fields
    confidence = Column(Float, nullable=True)  # AI confidence level (0-1)
    intent_matches = Column(JSONB, nullable=True)  # Matched intents from intent detection system
    # Example: [
    #   {"intent_name": "purchase_intent", "confidence": 0.85},
    #   {"intent_name": "pricing_inquiry", "confidence": 0.92}
    # ]

    # Attribution
    scored_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # For manual scores
    scored_by_agent_id = Column(Integer, ForeignKey("agents.id"), nullable=True)  # For AI scores
    conversation_session_id = Column(String, nullable=True)  # Related conversation

    # Timestamps
    scored_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    expires_at = Column(DateTime, nullable=True)  # For time-sensitive scores

    # Additional data
    score_metadata = Column(JSONB, nullable=True)  # Additional context (renamed from metadata to avoid SQLAlchemy conflict)

    # Relationships
    lead = relationship("Lead", back_populates="scores")
    company = relationship("Company")
    scored_by_user = relationship("User", foreign_keys=[scored_by_user_id])
    scored_by_agent = relationship("Agent", foreign_keys=[scored_by_agent_id])
