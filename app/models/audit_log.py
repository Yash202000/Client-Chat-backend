"""
Audit Log Model

Tracks all user actions across the platform for compliance and auditing.
"""
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from datetime import datetime

from app.core.database import Base


class AuditLog(Base):
    """
    Records every significant action taken by users within a company.
    """
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    # Action identifier e.g. "contact.created", "deal.updated", "template.deleted"
    action = Column(String(100), nullable=False, index=True)

    # Entity context
    entity_type = Column(String(50), nullable=True)   # contact, deal, lead, campaign, etc.
    entity_id = Column(Integer, nullable=True)
    entity_name = Column(String(255), nullable=True)  # denormalized display name

    # Detailed field-level changes: { "field": [old_value, new_value], ... }
    changes = Column(JSONB, nullable=True)

    ip_address = Column(String(45), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    # Relationships
    company = relationship("Company", backref="audit_logs")
    user = relationship("User", backref="audit_logs")

    # Composite indexes for efficient filtering
    __table_args__ = (
        Index("ix_audit_logs_company_created", "company_id", "created_at"),
        Index("ix_audit_logs_company_entity_type", "company_id", "entity_type"),
        Index("ix_audit_logs_company_action", "company_id", "action"),
    )

    def __repr__(self):
        return (
            f"<AuditLog(id={self.id}, action={self.action}, "
            f"entity={self.entity_type}:{self.entity_id})>"
        )
