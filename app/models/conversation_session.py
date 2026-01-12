from sqlalchemy import Boolean, Column, Integer, String, JSON, ForeignKey, DateTime, Text
from sqlalchemy.orm import relationship
from app.core.database import Base
import datetime

class ConversationSession(Base):
    __tablename__ = "conversation_sessions"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(String, unique=True, index=True, nullable=False)
    company_id = Column(Integer, ForeignKey("companies.id"))
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=True)
    assignee_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # User assigned to handle this conversation
    workflow_id = Column(Integer, ForeignKey("workflows.id"), nullable=True)
    contact_id = Column(Integer, ForeignKey("contacts.id"), nullable=True)
    next_step_id = Column(String, nullable=True) # The ID of the node to execute upon resumption
    
    channel = Column(String, nullable=False, default='web') # e.g., web, whatsapp, messenger
    context = Column(JSON, nullable=False, default={}) # Stores all collected variables
    status = Column(String, nullable=False, default='active') # e.g., active, paused, waiting_for_input, completed
    is_ai_enabled = Column(Boolean, nullable=False, default=True) # Whether the AI should respond automatically
    is_client_connected = Column(Boolean, nullable=False, default=False) # Whether the client is currently connected via WebSocket
    reopen_count = Column(Integer, nullable=False, default=0) # Number of times conversation has been reopened after resolution
    last_reopened_at = Column(DateTime, nullable=True) # Timestamp of most recent reopening
    resolved_at = Column(DateTime, nullable=True) # Timestamp when conversation was marked as resolved
    priority = Column(Integer, nullable=False, default=0) # 0=None, 1=Low, 2=Medium, 3=High, 4=Urgent

    # Human handoff fields
    handoff_requested_at = Column(DateTime, nullable=True) # When handoff to human was requested
    handoff_reason = Column(String, nullable=True) # Reason for handoff (e.g., 'customer_request', 'complex_issue', 'escalation')
    assigned_pool = Column(String, nullable=True) # Agent pool for assignment (e.g., 'support', 'sales')
    waiting_for_agent = Column(Boolean, nullable=False, default=False, server_default='false') # Client is waiting for human agent
    handoff_accepted_at = Column(DateTime, nullable=True) # When agent accepted the handoff

    # Subworkflow execution state
    subworkflow_stack = Column(JSON, nullable=True)  # Stack for nested subworkflow execution

    # AI-generated conversation summary
    summary = Column(Text, nullable=True)  # AI-generated summary of the conversation
    summary_generated_at = Column(DateTime, nullable=True)  # When summary was last generated

    # Agent-to-agent transfer tracking
    original_agent_id = Column(Integer, ForeignKey("agents.id"), nullable=True)  # First AI agent in conversation
    previous_agent_id = Column(Integer, ForeignKey("agents.id"), nullable=True)  # Agent before current transfer
    agent_transition_history = Column(JSON, nullable=True, default=[])  # History of agent transfers/consultations
    # Format: [{"from_agent_id": 1, "to_agent_id": 2, "type": "transfer"|"consult", "topic": "...", "timestamp": "..."}]
    handoff_summary = Column(Text, nullable=True)  # Summary passed during agent-to-agent handoff

    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    company = relationship("Company")
    agent = relationship("Agent", foreign_keys=[agent_id])  # Current agent handling the conversation
    original_agent = relationship("Agent", foreign_keys=[original_agent_id])  # First agent in conversation
    previous_agent = relationship("Agent", foreign_keys=[previous_agent_id])  # Agent before current transfer
    workflow = relationship("Workflow")
    contact = relationship("Contact", back_populates="sessions")
    messages = relationship("ChatMessage", back_populates="session")
