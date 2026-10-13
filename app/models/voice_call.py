from sqlalchemy import Column, Integer, String, ForeignKey, Boolean, DateTime, Float, Text, text
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
    full_transcript = Column(Text, nullable=True)

    # Recording
    recording_url = Column(String, nullable=True)
    recording_duration_secs = Column(Float, nullable=True)

    # CSAT (Phase 2)
    csat_score = Column(Integer, nullable=True)      # 1-5
    csat_sent_at = Column(DateTime, nullable=True)

    # Additional data
    call_metadata = Column(JSONB, nullable=True)

    # Contact centre (provider-neutral; LiveKit SIP calls use call_sid = SIP call id)
    provider = Column(String(32), nullable=False, default="twilio", server_default="twilio")
    room_name = Column(String(128), nullable=True, index=True)
    phone_number_id = Column(Integer, ForeignKey("phone_numbers.id", ondelete="SET NULL"), nullable=True)
    handled_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    ended_by = Column(String(32), nullable=True)  # caller | agent | system
    talk_seconds = Column(Float, nullable=True)
    hold_seconds = Column(Float, nullable=False, default=0, server_default="0")
    wrap_up_seconds = Column(Float, nullable=True)
    queue_id = Column(Integer, ForeignKey("call_queues.id", ondelete="SET NULL"), nullable=True)
    disposition_code_id = Column(Integer, ForeignKey("call_disposition_codes.id", ondelete="SET NULL"), nullable=True)
    disposition_note = Column(Text, nullable=True)
    hold_started_at = Column(DateTime, nullable=True)  # set while the caller is on hold
    manual_entry = Column(Boolean, nullable=False, default=False, server_default="false")  # CTI-down record (FR-CC-004)
    reconciled_with_call_id = Column(Integer, ForeignKey("voice_calls.id", ondelete="SET NULL"), nullable=True)
    recording_status = Column(String(16), nullable=True)  # starting | recording | paused | completed | failed | off
    recording_started_at = Column(DateTime, nullable=True)
    recording_ended_at = Column(DateTime, nullable=True)
    recording_egress_id = Column(String(64), nullable=True)
    recording_object_key = Column(String(512), nullable=True)  # object in MinIO / S3 (first part)
    # FR-CC-051: a paused recording is stored as parts: [{egress_id, key, started_at, ended_at, status, duration}]
    recording_parts = Column(JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"))
    recording_paused_at = Column(DateTime, nullable=True)
    quality = Column(JSONB, nullable=True)
    call_purpose_id = Column(Integer, ForeignKey("call_purpose_codes.id", ondelete="SET NULL"), nullable=True)
    outbound_result = Column(String(24), nullable=True)  # answered | no_answer | busy | invalid_number | failed
    missed_classification = Column(String(16), nullable=True)  # missed | abandoned | short_abandon  # jitter / packet loss / RTT reported by the agent's browser (NFR-007)

    # Relationships
    company = relationship("Company")
    agent = relationship("Agent")
    integration = relationship("Integration")
    contact = relationship("Contact")
    session = relationship("ConversationSession", foreign_keys=[conversation_id])
    handled_by = relationship("User", foreign_keys=[handled_by_user_id])
    phone_number = relationship("PhoneNumber")
    # passive_deletes: the database cascades (ON DELETE CASCADE) — deleting a call (e.g. retention) never
    # tries to null call_events.call_id, even if events are written concurrently
    events = relationship("CallEvent", back_populates="call", order_by="CallEvent.seq",
                          cascade="all, delete-orphan", passive_deletes=True)
