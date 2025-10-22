from sqlalchemy import Column, Integer, String, ForeignKey, Boolean, DateTime, Float, func, Table, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from app.core.database import Base

# Association table for intent-entity relationships
intent_entities = Table(
    'intent_entities',
    Base.metadata,
    Column('intent_id', Integer, ForeignKey('intents.id'), primary_key=True),
    Column('entity_id', Integer, ForeignKey('entities.id'), primary_key=True),
    Column('is_required', Boolean, default=False)
)

class Intent(Base):
    """Intent definitions for automatic workflow triggering"""
    __tablename__ = "intents"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    name = Column(String(100), nullable=False)  # e.g., "request_refund", "book_appointment"
    description = Column(Text)
    intent_category = Column(String(50))  # e.g., "support", "sales", "general"

    # Training data
    training_phrases = Column(JSONB, default=[])  # ["I want a refund", "refund please", ...]
    keywords = Column(JSONB, default=[])  # ["refund", "money back", ...]

    # Workflow routing
    trigger_workflow_id = Column(Integer, ForeignKey("workflows.id"), nullable=True)

    # Auto-trigger settings
    auto_trigger_enabled = Column(Boolean, default=True)
    require_agent_approval = Column(Boolean, default=False)  # For sensitive operations
    confidence_threshold = Column(Float, default=0.7)
    min_confidence_auto_trigger = Column(Float, default=0.7)

    # Metadata
    priority = Column(Integer, default=0)  # Higher priority intents checked first
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relationships
    company = relationship("Company", back_populates="intents")
    trigger_workflow = relationship("Workflow", foreign_keys=[trigger_workflow_id])
    entities = relationship("Entity", secondary=intent_entities, back_populates="intents")
    matches = relationship("IntentMatch", back_populates="intent")


class IntentMatch(Base):
    """Records of intent matches during conversations"""
    __tablename__ = "intent_matches"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(String(255), nullable=False, index=True)
    intent_id = Column(Integer, ForeignKey("intents.id"), nullable=False)

    # Match details
    message_text = Column(Text)
    confidence_score = Column(Float)
    matched_method = Column(String(50))  # "keyword", "similarity", "llm"
    extracted_entities = Column(JSONB, default={})

    # Workflow execution
    triggered_workflow_id = Column(Integer, ForeignKey("workflows.id"), nullable=True)
    workflow_executed = Column(Boolean, default=False)
    execution_status = Column(String(50))  # "success", "failed", "paused", "agent_intervened"

    # Metadata
    matched_at = Column(DateTime, server_default=func.now())

    # Relationships
    intent = relationship("Intent", back_populates="matches")
    triggered_workflow = relationship("Workflow", foreign_keys=[triggered_workflow_id])


class Entity(Base):
    """Named entities for extraction from messages"""
    __tablename__ = "entities"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    name = Column(String(100), nullable=False)  # e.g., "order_number", "email", "date"
    description = Column(Text)
    entity_type = Column(String(50))  # "text", "number", "email", "date", "phone", "custom"

    # Extraction configuration
    extraction_method = Column(String(50), default='llm')  # "llm", "regex", "keyword"
    validation_regex = Column(String(500), nullable=True)
    example_values = Column(JSONB, default=[])  # ["ORD-12345", "ORD-67890"]

    # Metadata
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relationships
    company = relationship("Company", back_populates="entities")
    intents = relationship("Intent", secondary=intent_entities, back_populates="entities")


class ConversationTag(Base):
    """Tags for organizing and categorizing conversations"""
    __tablename__ = "conversation_tags"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(String(255), nullable=False, index=True)
    tag = Column(String(50), nullable=False, index=True)

    # Metadata
    added_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    added_by_system = Column(Boolean, default=False)  # True if auto-tagged by workflow
    added_at = Column(DateTime, server_default=func.now())

    # Relationships
    added_by = relationship("User")
