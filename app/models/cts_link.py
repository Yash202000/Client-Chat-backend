from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from datetime import datetime
from app.core.database import Base


class CTSocialLink(Base):
    __tablename__ = "cts_links"

    id = Column(Integer, primary_key=True, index=True)
    link_key = Column(String(32), unique=True, index=True, nullable=False)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)

    channel = Column(String(20), nullable=False)   # whatsapp|instagram|telegram|messenger
    name = Column(String(255), nullable=False)
    handle = Column(String(255), nullable=False)   # phone for WA, username for others
    prefill_message = Column(String(500), nullable=True)

    utm_source = Column(String(100), nullable=True)
    utm_medium = Column(String(100), nullable=True)
    utm_campaign = Column(String(100), nullable=True)
    utm_content = Column(String(100), nullable=True)

    auto_tag = Column(String(100), nullable=True)
    workflow_id = Column(Integer, ForeignKey("workflows.id"), nullable=True)

    click_count = Column(Integer, default=0, nullable=False)
    contact_count = Column(Integer, default=0, nullable=False)

    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    company = relationship("Company", foreign_keys=[company_id])
    workflow = relationship("Workflow", foreign_keys=[workflow_id])


class CTSocialClick(Base):
    __tablename__ = "cts_clicks"

    id = Column(Integer, primary_key=True, index=True)
    link_id = Column(Integer, ForeignKey("cts_links.id"), nullable=False)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)

    referrer_url = Column(String(1000), nullable=True)
    user_agent = Column(String(500), nullable=True)
    ip_address = Column(String(64), nullable=True)
    contact_id = Column(Integer, ForeignKey("contacts.id"), nullable=True)

    clicked_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    converted_at = Column(DateTime, nullable=True)

    link = relationship("CTSocialLink", foreign_keys=[link_id])
    contact = relationship("Contact", foreign_keys=[contact_id])
