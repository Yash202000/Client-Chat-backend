
from sqlalchemy import Column, Integer, String, Boolean, ForeignKey
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

    company = relationship("Company")
