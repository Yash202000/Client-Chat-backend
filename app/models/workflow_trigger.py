from sqlalchemy import Column, Integer, String, ForeignKey, Boolean, Enum as SQLEnum
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import JSONB
from app.core.database import Base
import enum

class TriggerChannel(str, enum.Enum):
    """Enum for trigger channel types"""
    WEBSOCKET = "websocket"
    WHATSAPP = "whatsapp"
    TELEGRAM = "telegram"
    INSTAGRAM = "instagram"
    TWILIO_VOICE = "twilio_voice"
    FREESWITCH = "freeswitch"

class WorkflowTrigger(Base):
    """
    Model for workflow triggers that define when and how workflows are executed.

    Each trigger represents a channel entry point (WebSocket, WhatsApp, etc.) that
    can start a workflow execution when a message is received on that channel.
    """
    __tablename__ = "workflow_triggers"

    id = Column(Integer, primary_key=True, index=True)
    workflow_id = Column(Integer, ForeignKey("workflows.id"), nullable=False)

    # Trigger configuration
    channel = Column(SQLEnum(TriggerChannel), nullable=False, index=True)
    label = Column(String, nullable=True)  # User-friendly label for the trigger

    # Agent fallback configuration
    fallback_agent_id = Column(Integer, ForeignKey("agents.id"), nullable=True)

    # Trigger behavior
    auto_respond = Column(Boolean, default=True, nullable=False)
    # If True: workflow executes immediately on message receipt
    # If False: workflow waits for manual trigger

    # Status
    is_active = Column(Boolean, default=True, nullable=False)

    # Additional configuration stored as JSONB
    config = Column(JSONB, nullable=True)
    # Structure: {
    #   "filters": {  # Optional filters for triggering
    #     "user_tags": ["vip", "premium"],
    #     "conversation_status": ["open", "pending"]
    #   },
    #   "priority": 1,  # Execution priority if multiple triggers match
    #   "metadata": {}  # Any additional channel-specific config
    # }

    # Relationships
    workflow = relationship("Workflow", back_populates="triggers", foreign_keys=[workflow_id])
    fallback_agent = relationship("Agent", foreign_keys=[fallback_agent_id])
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    company = relationship("Company", back_populates="workflow_triggers", foreign_keys=[company_id])
