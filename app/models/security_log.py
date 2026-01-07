"""
Security Log Model

Stores security events including prompt injection attempts, rate limit violations,
and other security-related events for auditing and analysis.
"""
from sqlalchemy import Column, Integer, String, DateTime, Text, JSON, ForeignKey, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class SecurityLog(Base):
    """
    Logs security events for auditing and threat analysis.
    """
    __tablename__ = "security_logs"

    id = Column(Integer, primary_key=True, index=True)

    # Event classification
    event_type = Column(String(50), nullable=False, index=True)
    # Types: "prompt_injection", "rate_limit", "output_leak", "suspicious_activity"

    threat_level = Column(String(20), nullable=False, index=True)
    # Levels: "none", "low", "medium", "high", "critical"

    # Context
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, index=True)
    session_id = Column(String(255), nullable=True, index=True)
    user_ip = Column(String(45), nullable=True)  # IPv6 max length

    # Attack details
    blocked = Column(Integer, default=1)  # 1 = blocked, 0 = allowed but logged
    original_message = Column(Text, nullable=True)  # The attempted injection
    detected_patterns = Column(JSON, nullable=True)  # List of patterns matched
    sanitized_message = Column(Text, nullable=True)  # Message after sanitization

    # Additional metadata
    channel = Column(String(50), nullable=True)  # websocket, whatsapp, telegram, etc.
    user_agent = Column(String(500), nullable=True)
    additional_data = Column(JSON, nullable=True)  # Any extra context

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    # Relationships
    company = relationship("Company", backref="security_logs")

    # Indexes for efficient querying
    __table_args__ = (
        Index('ix_security_logs_company_created', 'company_id', 'created_at'),
        Index('ix_security_logs_event_threat', 'event_type', 'threat_level'),
    )

    def __repr__(self):
        return f"<SecurityLog(id={self.id}, type={self.event_type}, threat={self.threat_level}, blocked={self.blocked})>"
