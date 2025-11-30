
from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, Text
from sqlalchemy.orm import relationship
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

    company = relationship("Company")
