from sqlalchemy import Column, Integer, String, ForeignKey, Boolean, DateTime, Float, Text
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import JSONB
from app.core.database import Base
import datetime
import enum


class CallStatus(str, enum.Enum):
    """Status of a voice call"""
    RINGING = "ringing"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    NO_ANSWER = "no_answer"
    BUSY = "busy"


class VoiceCall(Base):
    """
    Model for tracking Twilio voice calls.

    Each record represents a single voice call with its state, timing,
    and relationship to the conversation session.
    """
    __tablename__ = "voice_calls"

    id = Column(Integer, primary_key=True, index=True)
    call_sid = Column(String, unique=True, index=True, nullable=False)  # Twilio Call SID
    stream_sid = Column(String, unique=True, nullable=True)  # Media Stream SID

    # Caller/Callee info
    from_number = Column(String, nullable=False)
    to_number = Column(String, nullable=False)  # Twilio number

    # Company mapping
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=True)
    integration_id = Column(Integer, ForeignKey("integrations.id"), nullable=True)

    # Session linkage
    conversation_id = Column(String, ForeignKey("conversation_sessions.conversation_id"), nullable=True)
    contact_id = Column(Integer, ForeignKey("contacts.id"), nullable=True)

    # Call state
    status = Column(String, default=CallStatus.RINGING.value)
    direction = Column(String, default="inbound")  # inbound/outbound

    # Timing
    started_at = Column(DateTime, default=datetime.datetime.utcnow)
    answered_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)
    duration_seconds = Column(Float, nullable=True)

    # Transcription
    full_transcript = Column(Text, nullable=True)  # Full conversation transcript

    # Additional data
    call_metadata = Column(JSONB, nullable=True)  # Additional call data

    # Relationships
    company = relationship("Company")
    agent = relationship("Agent")
    integration = relationship("Integration")
    contact = relationship("Contact")
    session = relationship("ConversationSession", foreign_keys=[conversation_id])
