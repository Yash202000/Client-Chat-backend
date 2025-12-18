"""
WorkflowTemplate Model
Stores pre-built system templates and user-saved workflow templates
"""
from sqlalchemy import Column, Integer, String, Text, Boolean, ForeignKey, DateTime, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from app.core.database import Base


class WorkflowTemplate(Base):
    __tablename__ = "workflow_templates"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    category = Column(String, nullable=True, index=True)  # e.g., "Customer Support", "Sales"
    icon = Column(String, nullable=True)  # Icon name for UI display

    # Template content (same structure as Workflow)
    visual_steps = Column(JSONB, nullable=False)  # {nodes: [], edges: []}
    trigger_phrases = Column(JSONB, default=list)
    intent_config = Column(JSONB, nullable=True)

    # Ownership - NULL means system template
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, index=True)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    # Metadata
    is_system = Column(Boolean, default=False, index=True)  # True for pre-built templates
    is_active = Column(Boolean, default=True)
    usage_count = Column(Integer, default=0)  # Track popularity
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())

    # Relationships
    company = relationship("Company")
    created_by = relationship("User")
