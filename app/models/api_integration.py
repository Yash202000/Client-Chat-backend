from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, DateTime, JSON
from sqlalchemy.orm import relationship
from app.core.database import Base
import datetime


class ApiIntegration(Base):
    """
    Model for API integrations that allow third-party systems to communicate
    with agents via REST API.

    Each integration is linked to an API key and defines how responses are
    delivered (sync or webhook), default agent/workflow, and rate limiting.
    """
    __tablename__ = "api_integrations"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)

    # Link to API key for authentication (one-to-one)
    api_key_id = Column(Integer, ForeignKey("api_keys.id"), nullable=False, unique=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)

    # Webhook configuration for async responses
    webhook_url = Column(String, nullable=True)
    webhook_secret = Column(String, nullable=True)  # Secret for HMAC signature verification
    webhook_enabled = Column(Boolean, default=False, nullable=False)

    # Default behavior settings
    sync_response = Column(Boolean, default=True, nullable=False)  # Wait for response in request
    default_agent_id = Column(Integer, ForeignKey("agents.id"), nullable=True)
    default_workflow_id = Column(Integer, ForeignKey("workflows.id"), nullable=True)

    # Rate limiting overrides (per integration)
    rate_limit_requests = Column(Integer, nullable=True)  # Requests per window
    rate_limit_window = Column(Integer, nullable=True)  # Window in seconds

    # Status
    is_active = Column(Boolean, default=True, nullable=False)

    # Additional configuration
    extra_config = Column(JSON, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    # Relationships
    api_key = relationship("ApiKey", backref="api_integration", uselist=False)
    company = relationship("Company", backref="api_integrations")
    default_agent = relationship("Agent", foreign_keys=[default_agent_id])
    default_workflow = relationship("Workflow", foreign_keys=[default_workflow_id])
