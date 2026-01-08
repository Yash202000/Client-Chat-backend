"""
Token Usage Model

Tracks LLM API token consumption per request for cost visibility and budget management.
"""
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class TokenUsage(Base):
    """
    Logs token usage for each LLM API call.

    Supports three tracking modes (configured in CompanySettings):
    - none: No tracking
    - aggregated: Only daily/hourly aggregates stored
    - detailed: Every request logged individually
    """
    __tablename__ = "token_usage"

    id = Column(Integer, primary_key=True, index=True)

    # Context
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=True, index=True)
    session_id = Column(String(255), nullable=True, index=True)  # conversation_id

    # LLM Details
    provider = Column(String(50), nullable=False)  # openai, groq, gemini
    model_name = Column(String(100), nullable=False)

    # Token Counts
    prompt_tokens = Column(Integer, nullable=False, default=0)
    completion_tokens = Column(Integer, nullable=False, default=0)
    total_tokens = Column(Integer, nullable=False, default=0)

    # Cost (estimated in USD cents for precision)
    estimated_cost_cents = Column(Integer, nullable=True)

    # Request context
    request_type = Column(String(50), nullable=True)  # chat, workflow, summary, tool, suggestion

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    # Relationships
    company = relationship("Company", backref="token_usage_logs")
    agent = relationship("Agent", backref="token_usage_logs")

    # Composite indexes for efficient querying
    __table_args__ = (
        Index('ix_token_usage_company_created', 'company_id', 'created_at'),
        Index('ix_token_usage_agent_created', 'agent_id', 'created_at'),
        Index('ix_token_usage_provider_model', 'provider', 'model_name'),
    )

    def __repr__(self):
        return f"<TokenUsage(id={self.id}, provider={self.provider}, tokens={self.total_tokens}, cost={self.estimated_cost_cents})>"
