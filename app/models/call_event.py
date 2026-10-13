from sqlalchemy import Column, Integer, BigInteger, String, ForeignKey, DateTime, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class CallEvent(Base):
    """
    Ordered CTI event log for a call (offer, ring, answer, hold, transfer, end, dtmf, ...).
    seq is assigned per call under a row lock on the call, so events are gap-free and ordered (NFR-004).
    """
    __tablename__ = "call_events"
    __table_args__ = (UniqueConstraint("call_id", "seq", name="uq_call_events_call_seq"),)

    id = Column(BigInteger, primary_key=True)
    call_id = Column(Integer, ForeignKey("voice_calls.id", ondelete="CASCADE"), nullable=False, index=True)
    seq = Column(Integer, nullable=False)
    type = Column(String(48), nullable=False)
    at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    actor_type = Column(String(16), nullable=False, default="system", server_default="system")  # system|caller|agent|ai|supervisor
    actor_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    payload = Column(JSONB, nullable=False, default=dict)

    call = relationship("VoiceCall", back_populates="events")


class CallLeg(Base):
    """
    One party's stage of a call (FR-CC-028 transfer chain): the AI, each agent (in order), consults,
    supervisors. Ordered by seq; end_reason / transferred_to record how each stage ended.
    """
    __tablename__ = "call_legs"
    __table_args__ = (UniqueConstraint("call_id", "seq", name="uq_call_legs_call_seq"),)

    id = Column(Integer, primary_key=True)
    call_id = Column(Integer, ForeignKey("voice_calls.id", ondelete="CASCADE"), nullable=False, index=True)
    seq = Column(Integer, nullable=False)
    kind = Column(String(16), nullable=False)  # ai | agent | consult | supervisor | external
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    party = Column(String(128), nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    ended_at = Column(DateTime(timezone=True), nullable=True)
    end_reason = Column(String(32), nullable=True)
    transferred_to = Column(String(128), nullable=True)
