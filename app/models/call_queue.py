from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Float
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import JSONB
from app.core.database import Base
import datetime


class CallQueueEntry(Base):
    __tablename__ = "call_queue_entries"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)

    # Call identification
    call_sid = Column(String, index=True, nullable=False)   # Twilio SID or FreeSWITCH UUID
    source = Column(String, nullable=False, default="twilio")  # "twilio" | "freeswitch"

    # Caller details
    caller_number = Column(String, nullable=False)
    caller_name = Column(String, nullable=True)

    # Session linkage
    session_id = Column(String, ForeignKey("conversation_sessions.conversation_id"), nullable=True)
    contact_id = Column(Integer, ForeignKey("contacts.id"), nullable=True)

    # Queue state
    # waiting | ringing | connected | abandoned | timeout | transferred | voicemail
    status = Column(String, nullable=False, default="waiting", index=True)
    priority = Column(Integer, nullable=False, default=0)  # 0=normal 1=high 2=urgent

    # Skills-based routing (Phase 2)
    required_skill = Column(String, nullable=True)

    # Timing
    entered_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    ringing_at = Column(DateTime, nullable=True)
    connected_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)
    estimated_wait_secs = Column(Integer, nullable=True)

    # Voicemail / overflow (Phase 2)
    voicemail_url = Column(String, nullable=True)
    overflow_at = Column(DateTime, nullable=True)

    # Agent assignment
    assigned_agent_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    extra = Column(JSONB, nullable=True)

    # Relationships
    company = relationship("Company")
    session = relationship("ConversationSession", foreign_keys=[session_id])
    contact = relationship("Contact")
    assigned_agent = relationship("User", foreign_keys=[assigned_agent_id])
