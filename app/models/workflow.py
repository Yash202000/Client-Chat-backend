from sqlalchemy import Column, Integer, String, Text, JSON, ForeignKey, Boolean, Table
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import JSONB
from app.core.database import Base

# Junction table for many-to-many relationship between agents and workflows
agent_workflows = Table(
    'agent_workflows',
    Base.metadata,
    Column('agent_id', Integer, ForeignKey('agents.id', ondelete='CASCADE'), primary_key=True),
    Column('workflow_id', Integer, ForeignKey('workflows.id', ondelete='CASCADE'), primary_key=True)
)


class Workflow(Base):
    __tablename__ = "workflows"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    description = Column(String, nullable=True)
    # agent_id removed - now using many-to-many via agent_workflows table
    steps = Column(JSON, nullable=False)
    visual_steps = Column(JSON, nullable=True)
    trigger_phrases = Column(JSON, nullable=True)

    # Intent Configuration (NEW)
    intent_config = Column(JSONB, nullable=True, default=None)
    # Structure: {
    #   "enabled": true/false,
    #   "trigger_intents": [
    #     {
    #       "id": "unique_id",
    #       "name": "request_refund",
    #       "keywords": ["refund", "money back"],
    #       "training_phrases": ["I want a refund", ...],
    #       "confidence_threshold": 0.7
    #     }
    #   ],
    #   "entities": [
    #     {
    #       "name": "order_number",
    #       "type": "text",
    #       "extraction_method": "llm",
    #       "validation_regex": "^ORD-[0-9]{6}$",
    #       "required": true,
    #       "prompt_if_missing": "What's your order number?"
    #     }
    #   ],
    #   "auto_trigger_enabled": true,
    #   "min_confidence": 0.75
    # }

    # Versioning fields
    version = Column(Integer, default=1, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    
    # Self-referencing foreign key for versioning
    parent_workflow_id = Column(Integer, ForeignKey("workflows.id"), nullable=True)
    
    # Relationships
    agents = relationship("Agent", secondary=agent_workflows, back_populates="workflows")
    parent_workflow = relationship("Workflow", remote_side=[id], back_populates="versions")
    versions = relationship("Workflow", back_populates="parent_workflow")
    triggers = relationship("WorkflowTrigger", back_populates="workflow", cascade="all, delete-orphan")
    company_id = Column(Integer, ForeignKey("companies.id"))
    company = relationship("Company", back_populates="workflows")
    campaigns = relationship("Campaign", back_populates="workflow")

# Add back-population to Company model
from app.models.company import Company
Company.workflows = relationship("Workflow", order_by=Workflow.id, back_populates="company")
