from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, DateTime, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from datetime import datetime
from app.core.database import Base


class CTWALink(Base):
    __tablename__ = "ctwa_links"

    id = Column(Integer, primary_key=True, index=True)
    link_key = Column(String(32), unique=True, index=True, nullable=False)  # short public key
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)

    # Identification
    name = Column(String(255), nullable=False)           # internal label, e.g. "Summer Sale"
    phone_number = Column(String(30), nullable=False)    # WhatsApp number to open

    # Pre-fill message
    prefill_message = Column(String(500), nullable=True)

    # UTM / attribution
    utm_source = Column(String(100), nullable=True)
    utm_medium = Column(String(100), nullable=True)
    utm_campaign = Column(String(100), nullable=True)
    utm_content = Column(String(100), nullable=True)

    # Auto-tag contacts that come via this link
    auto_tag = Column(String(100), nullable=True)        # tag name to apply on first contact

    # Workflow/sequence to trigger on first message
    workflow_id = Column(Integer, ForeignKey("workflows.id"), nullable=True)

    # Stats
    click_count = Column(Integer, default=0, nullable=False)
    contact_count = Column(Integer, default=0, nullable=False)  # unique contacts created

    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    company = relationship("Company", foreign_keys=[company_id])
    workflow = relationship("Workflow", foreign_keys=[workflow_id])


class CTWAClick(Base):
    __tablename__ = "ctwa_clicks"

    id = Column(Integer, primary_key=True, index=True)
    link_id = Column(Integer, ForeignKey("ctwa_links.id"), nullable=False)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)

    # Attribution
    referrer_url = Column(String(1000), nullable=True)
    user_agent = Column(String(500), nullable=True)
    ip_address = Column(String(64), nullable=True)

    # Contact created from this click (set when first WA message arrives)
    contact_id = Column(Integer, ForeignKey("contacts.id"), nullable=True)

    clicked_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    converted_at = Column(DateTime, nullable=True)       # when first WA message received

    link = relationship("CTWALink", foreign_keys=[link_id])
    contact = relationship("Contact", foreign_keys=[contact_id])
