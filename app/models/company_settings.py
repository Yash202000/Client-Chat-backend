
from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, Text, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base

class CompanySettings(Base):
    __tablename__ = "company_settings"

    id = Column(Integer, primary_key=True, index=True)
    company_name = Column(String, default="AgentConnect")
    support_email = Column(String, default="support@agentconnect.com")
    timezone = Column(String, default="UTC")
    language = Column(String, default="en")
    business_hours = Column(Boolean, default=True)
    logo_url = Column(String, nullable=True)
    primary_color = Column(String, nullable=True)
    secondary_color = Column(String, nullable=True)
    custom_domain = Column(String, nullable=True)
    company_id = Column(Integer, ForeignKey("companies.id"))

    # SMTP Email Configuration
    smtp_host = Column(String, nullable=True)
    smtp_port = Column(Integer, default=587)
    smtp_user = Column(String, nullable=True)
    smtp_password = Column(Text, nullable=True)  # Should be encrypted in production
    smtp_use_tls = Column(Boolean, default=True)
    smtp_from_email = Column(String, nullable=True)
    smtp_from_name = Column(String, nullable=True)

    # Token Usage Tracking Settings
    token_tracking_mode = Column(String(20), default="detailed")  # none, aggregated, detailed
    monthly_budget_cents = Column(Integer, nullable=True)  # Monthly spending limit in cents
    alert_threshold_percent = Column(Integer, default=80)  # Alert at this % of budget
    alert_email = Column(String(255), nullable=True)  # Email for cost alerts
    alerts_enabled = Column(Boolean, default=True)
    per_agent_daily_limit_cents = Column(Integer, nullable=True)  # Optional per-agent limit

    company = relationship("Company")
