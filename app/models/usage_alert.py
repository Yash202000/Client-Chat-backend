"""
Usage Alert Model

Stores alerts triggered when token usage exceeds configured thresholds.
"""
from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, ForeignKey, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class UsageAlert(Base):
    """
    Stores cost/usage alerts for budget management.

    Alert types:
    - budget_warning: Approaching monthly budget threshold
    - budget_exceeded: Monthly budget exceeded
    - daily_limit: Agent daily limit exceeded
    """
    __tablename__ = "usage_alerts"

    id = Column(Integer, primary_key=True, index=True)

    # Context
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=True)  # Optional: for agent-specific alerts

    # Alert details
    alert_type = Column(String(50), nullable=False, index=True)
    # Types: "budget_warning", "budget_exceeded", "daily_limit"

    threshold_value = Column(Integer, nullable=False)  # The limit that was configured (in cents)
    current_value = Column(Integer, nullable=False)  # Current spending when alert triggered (in cents)
    message = Column(Text, nullable=True)  # Human-readable alert message

    # Acknowledgment
    acknowledged = Column(Boolean, default=False)
    acknowledged_at = Column(DateTime(timezone=True), nullable=True)
    acknowledged_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    # Relationships
    company = relationship("Company", backref="usage_alerts")
    agent = relationship("Agent", backref="usage_alerts")
    acknowledger = relationship("User", backref="acknowledged_alerts")

    # Composite indexes
    __table_args__ = (
        Index('ix_usage_alerts_company_created', 'company_id', 'created_at'),
        Index('ix_usage_alerts_company_unack', 'company_id', 'acknowledged'),
    )

    def __repr__(self):
        return f"<UsageAlert(id={self.id}, type={self.alert_type}, acknowledged={self.acknowledged})>"
