from sqlalchemy import Column, Integer, String, ForeignKey, Boolean, DateTime, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class PhoneNumber(Base):
    """
    Provider-neutral phone number (DID) used by the contact centre.

    Each number routes inbound calls to an entry workflow (IVR) and/or a default AI agent.
    Starts with provider "livekit_sip"; Twilio / FreeSWITCH numbers keep their own tables for now.
    """
    __tablename__ = "phone_numbers"
    __table_args__ = (UniqueConstraint("provider", "number", name="uq_phone_numbers_provider_number"),)

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)

    # E.164 (+966...) or a short code / extension such as "980"
    number = Column(String(32), nullable=False, index=True)
    friendly_name = Column(String(255), nullable=True)
    provider = Column(String(32), nullable=False, default="livekit_sip")

    # Routing: entry workflow (IVR) runs first; default agent answers when no workflow is set
    entry_workflow_id = Column(Integer, ForeignKey("workflows.id", ondelete="SET NULL"), nullable=True)
    default_agent_id = Column(Integer, ForeignKey("agents.id", ondelete="SET NULL"), nullable=True)

    # "ai": the voice process answers (entry workflow / AI agent). "direct": ring human agents' browsers.
    routing_mode = Column(String(16), nullable=False, default="ai", server_default="ai")
    # Team whose online members ring in direct mode; empty = every online user of the company
    ring_team_id = Column(Integer, ForeignKey("teams.id", ondelete="SET NULL"), nullable=True)
    # Queue (ACD) that agents are offered calls from; takes precedence over ring_team_id
    queue_id = Column(Integer, ForeignKey("call_queues.id", ondelete="SET NULL"), nullable=True)

    language = Column(String(16), nullable=False, default="en")
    recording_enabled = Column(Boolean, nullable=False, default=True)
    is_active = Column(Boolean, nullable=False, default=True)

    # Provider-side identifiers (e.g. LiveKit inbound trunk / dispatch rule ids) and extra settings
    provider_config = Column(JSONB, nullable=False, default=dict)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    company = relationship("Company")
    entry_workflow = relationship("Workflow")
    default_agent = relationship("Agent")
    ring_team = relationship("Team")
