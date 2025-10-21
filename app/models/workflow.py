from sqlalchemy import Column, Integer, String, Text, JSON, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import JSONB
from app.core.database import Base

class Workflow(Base):
    __tablename__ = "workflows"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    description = Column(String, nullable=True)
    agent_id = Column(Integer, ForeignKey("agents.id"))
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
    agent = relationship("Agent", back_populates="workflows")
    parent_workflow = relationship("Workflow", remote_side=[id], back_populates="versions")
    versions = relationship("Workflow", back_populates="parent_workflow")
    triggers = relationship("WorkflowTrigger", back_populates="workflow", cascade="all, delete-orphan")
    company_id = Column(Integer, ForeignKey("companies.id"))
    company = relationship("Company", back_populates="workflows")

# Add back-population to Company model
from app.models.company import Company
Company.workflows = relationship("Workflow", order_by=Workflow.id, back_populates="company")
