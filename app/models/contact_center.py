"""
Contact-centre configuration and agent state (M3): queues, agent states, reason / disposition
codes, shifts, extensions and the number directory.
"""
from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base

# Agent states (FR-CC-046). "not ready" states require a reason code (FR-CC-047).
AGENT_STATES = ("ready", "on_call", "wrap_up", "break", "training", "meeting", "unavailable", "logged_out")
NOT_READY_STATES = ("break", "training", "meeting", "unavailable")


class CallQueue(Base):
    """A queue calls wait in until an agent is offered the call (ACD)."""
    __tablename__ = "call_queues"
    __table_args__ = (UniqueConstraint("company_id", "name", name="uq_call_queues_company_name"),)

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    name = Column(String(128), nullable=False)
    description = Column(String(512), nullable=True)
    priority = Column(Integer, nullable=False, default=0, server_default="0")  # higher = served first across queues
    required_skill = Column(String(64), nullable=True)
    is_open = Column(Boolean, nullable=False, default=True, server_default="true")  # closed queues refuse transfers
    is_supervisor_queue = Column(Boolean, nullable=False, default=False, server_default="false")
    # How long each agent is offered a call before it moves to the next agent
    offer_timeout_seconds = Column(Integer, nullable=False, default=20, server_default="20")
    # After this wait the overflow action runs (voice process plays overflow message / gives back to AI)
    max_wait_seconds = Column(Integer, nullable=False, default=120, server_default="120")
    overflow_text = Column(Text, nullable=True)
    wrap_up_seconds = Column(Integer, nullable=False, default=30, server_default="30")  # after-call work (FR-CC-020)
    # FR-CC-013: tell waiting callers their position and expected wait (on entry, then every interval)
    announce_wait_time = Column(Boolean, nullable=False, default=False, server_default="false")
    announce_interval_seconds = Column(Integer, nullable=False, default=60, server_default="60")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    members = relationship("CallQueueMember", back_populates="queue", cascade="all, delete-orphan")


class CallQueueMember(Base):
    __tablename__ = "call_queue_members"
    __table_args__ = (UniqueConstraint("queue_id", "user_id", name="uq_call_queue_members"),)

    id = Column(Integer, primary_key=True)
    queue_id = Column(Integer, ForeignKey("call_queues.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    tier = Column(Integer, nullable=False, default=1, server_default="1")  # lower tier offered first

    queue = relationship("CallQueue", back_populates="members")
    user = relationship("User")


class AgentState(Base):
    """Current contact-centre state of a user (one row per user)."""
    __tablename__ = "agent_states"

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    state = Column(String(16), nullable=False, default="logged_out")
    reason_code_id = Column(Integer, ForeignKey("agent_reason_codes.id", ondelete="SET NULL"), nullable=True)
    since = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_call_ended_at = Column(DateTime(timezone=True), nullable=True)  # longest-idle routing
    current_call_id = Column(Integer, ForeignKey("voice_calls.id", ondelete="SET NULL"), nullable=True)

    reason_code = relationship("AgentReasonCode")


class AgentStateHistory(Base):
    """Every state change with its duration once closed (RPT-07 agent status report)."""
    __tablename__ = "agent_state_history"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    state = Column(String(16), nullable=False)
    reason_code_id = Column(Integer, ForeignKey("agent_reason_codes.id", ondelete="SET NULL"), nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    ended_at = Column(DateTime(timezone=True), nullable=True)
    changed_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    source = Column(String(16), nullable=False, default="manual")  # manual | call | system


class AgentReasonCode(Base):
    """Not-ready reasons (FR-CC-047), e.g. Prayer, Lunch, Training."""
    __tablename__ = "agent_reason_codes"

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    name = Column(String(64), nullable=False)
    state = Column(String(16), nullable=False, default="break")  # which not-ready state it puts the agent in
    allowed_role_ids = Column(JSONB, nullable=True)  # null = every role
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")


class DispositionCode(Base):
    """Call result codes chosen during after-call work (FR-CC-020)."""
    __tablename__ = "call_disposition_codes"

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    name = Column(String(64), nullable=False)
    requires_note = Column(Boolean, nullable=False, default=False, server_default="false")
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")


class Shift(Base):
    """Working schedule; agents assigned to shifts only get calls while on shift (FR-CC-009)."""
    __tablename__ = "agent_shifts"

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    name = Column(String(64), nullable=False)
    timezone = Column(String(64), nullable=False, default="Asia/Riyadh")
    # [{"days": [0..6, Mon=0], "start": "08:00", "end": "16:00"}]
    schedule = Column(JSONB, nullable=False, default=list)
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")


class ShiftAssignment(Base):
    __tablename__ = "agent_shift_assignments"
    __table_args__ = (UniqueConstraint("shift_id", "user_id", name="uq_agent_shift_assignments"),)

    id = Column(Integer, primary_key=True)
    shift_id = Column(Integer, ForeignKey("agent_shifts.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(16), nullable=False, default="agent")  # agent | supervisor


class Extension(Base):
    """Internal extension of a user (FR-CC-029/032); replaces the browser-only localStorage list."""
    __tablename__ = "user_extensions"
    __table_args__ = (UniqueConstraint("company_id", "extension", name="uq_user_extensions_company_ext"),)

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)
    extension = Column(String(16), nullable=False)


class DirectoryEntry(Base):
    """Number directory: entities and external numbers (FR-CC-032). Blocked entries can't be dialled / transferred to."""
    __tablename__ = "phone_directory_entries"

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    name = Column(String(128), nullable=False)
    number = Column(String(32), nullable=False)
    kind = Column(String(16), nullable=False, default="external")  # entity | external
    transfer_allowed = Column(Boolean, nullable=False, default=False, server_default="false")
    notes = Column(String(255), nullable=True)


class ContactCenterSettings(Base):
    """Company-wide contact-centre settings (missed-call rules, outbound calling)."""
    __tablename__ = "contact_center_settings"

    company_id = Column(Integer, ForeignKey("companies.id"), primary_key=True)
    # Callers who hang up within this many seconds of queueing are "short abandons", excluded from tasks (FR-CC-036)
    abandon_threshold_seconds = Column(Integer, nullable=False, default=5, server_default="5")
    create_callback_tasks = Column(Boolean, nullable=False, default=True, server_default="true")  # BR-005
    default_country_code = Column(String(8), nullable=False, default="+966", server_default="+966")
    allowed_country_codes = Column(JSONB, nullable=False, default=lambda: ["+966"])
    outbound_caller_number = Column(String(32), nullable=True)  # number presented to callees
    outbound_trunk_address = Column(String(255), nullable=True)  # SIP provider host[:port]
    outbound_auth_username = Column(String(128), nullable=True)
    outbound_auth_password = Column(String(255), nullable=True)
    outbound_trunk_id = Column(String(64), nullable=True)  # LiveKit outbound trunk (managed)
    refusal_comment_required = Column(Boolean, nullable=False, default=True, server_default="true")
    # Data retention (FR-ADM-008): null = keep for life; otherwise at least 90 days
    recording_retention_days = Column(Integer, nullable=True)
    call_history_retention_days = Column(Integer, nullable=True)
    chat_retention_days = Column(Integer, nullable=True)
    retention_changed_at = Column(DateTime(timezone=True), nullable=True)  # 7-day grace after shortening
    service_level_seconds = Column(Integer, nullable=False, default=20, server_default="20")  # answered within = SL
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class BlockedNumber(Base):
    """Numbers that may not be called (outbound) or are rejected (inbound) — FR-CC-044."""
    __tablename__ = "number_blocklist"
    __table_args__ = (UniqueConstraint("company_id", "number", name="uq_number_blocklist"),)

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    number = Column(String(32), nullable=False)
    scope = Column(String(16), nullable=False, default="outbound")
    reason = Column(String(255), nullable=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class CallPurposeCode(Base):
    """Why an agent makes an outbound call (FR-CC-043): callback, data completion, reference number…"""
    __tablename__ = "call_purpose_codes"

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    name = Column(String(64), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")


class MissedCallTask(Base):
    """A missed / abandoned call to follow up (BR-005, FR-CC-035..040). Closed only with a result."""
    __tablename__ = "missed_call_tasks"

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    call_id = Column(Integer, ForeignKey("voice_calls.id", ondelete="CASCADE"), nullable=False, unique=True)
    caller_number = Column(String(32), nullable=False, index=True)
    contact_id = Column(Integer, ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True)
    queue_id = Column(Integer, ForeignKey("call_queues.id", ondelete="SET NULL"), nullable=True)
    classification = Column(String(16), nullable=False)  # missed | abandoned
    loss_reason = Column(String(48), nullable=True)
    wait_seconds = Column(Float, nullable=True)
    status = Column(String(16), nullable=False, default="open", server_default="open")  # open | assigned | closed
    assigned_to_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    assigned_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    assigned_at = Column(DateTime(timezone=True), nullable=True)
    result = Column(String(24), nullable=True)
    result_comment = Column(Text, nullable=True)
    closed_at = Column(DateTime(timezone=True), nullable=True)
    closed_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    attempts = Column(Integer, nullable=False, default=0, server_default="0")
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class CallbackAttempt(Base):
    __tablename__ = "callback_attempts"

    id = Column(Integer, primary_key=True)
    task_id = Column(Integer, ForeignKey("missed_call_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    voice_call_id = Column(Integer, ForeignKey("voice_calls.id", ondelete="SET NULL"), nullable=True)
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    ended_at = Column(DateTime(timezone=True), nullable=True)
    result = Column(String(24), nullable=True)
    duration_seconds = Column(Float, nullable=True)


class QaForm(Base):
    """Quality evaluation form (FR-CC-053 / RPT-09): weighted criteria and a pass score."""
    __tablename__ = "qa_forms"

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    name = Column(String(128), nullable=False)
    criteria = Column(JSONB, nullable=False, default=list)  # [{"key", "label", "weight"}]
    pass_score = Column(Integer, nullable=False, default=70, server_default="70")
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class QaEvaluation(Base):
    """One call sampled for review; completed with per-criterion scores, notes and an improvement plan."""
    __tablename__ = "qa_evaluations"

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    form_id = Column(Integer, ForeignKey("qa_forms.id", ondelete="SET NULL"), nullable=True)
    call_id = Column(Integer, ForeignKey("voice_calls.id", ondelete="CASCADE"), nullable=False, index=True)
    agent_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    evaluator_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    status = Column(String(16), nullable=False, default="pending", server_default="pending")
    scores = Column(JSONB, nullable=False, default=dict)  # {"greeting": 8, ...} out of each weight
    total_score = Column(Float, nullable=True)  # percentage
    passed = Column(Boolean, nullable=True)
    notes = Column(Text, nullable=True)
    improvement_plan = Column(Text, nullable=True)
    sample_batch = Column(String(32), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)


class SipAccount(Base):
    """
    SIP phone login for a system user (softphones such as PortSIP register with the Kamailio registrar).
    Only the SIP digest hash is stored: ha1 = md5(username:realm:password). The registrar reads the
    kamailio_subscriber view, which lists active users with an enabled account only.
    """
    __tablename__ = "sip_accounts"

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)
    username = Column(String(32), nullable=False, unique=True)
    ha1 = Column(String(32), nullable=False)
    realm = Column(String(64), nullable=False)
    enabled = Column(Boolean, nullable=False, default=True, server_default="true")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
