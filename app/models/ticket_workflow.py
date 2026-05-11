from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime, Boolean, Enum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from datetime import datetime
import enum
from app.core.database import Base


class StatusCategory(str, enum.Enum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    DONE = "done"


class TicketWorkflow(Base):
    __tablename__ = "ticket_workflows"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)

    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    is_default = Column(Boolean, default=False, nullable=False)
    # "lead" | "deal" | "contact" | None (ticket-project workflows)
    entity_type = Column(String, nullable=True, index=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    company = relationship("Company", back_populates="ticket_workflows")
    statuses = relationship("TicketStatus", back_populates="workflow",
                            cascade="all, delete-orphan", order_by="TicketStatus.position")
    transitions = relationship("TicketTransition", back_populates="workflow",
                               cascade="all, delete-orphan")


class TicketStatus(Base):
    __tablename__ = "ticket_statuses"

    id = Column(Integer, primary_key=True, index=True)
    workflow_id = Column(Integer, ForeignKey("ticket_workflows.id"), nullable=False, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)

    name = Column(String, nullable=False)
    color = Column(String(7), nullable=False, default="#6366f1")
    category = Column(Enum(StatusCategory), nullable=False, default=StatusCategory.TODO)
    position = Column(Integer, nullable=False, default=0)
    is_default = Column(Boolean, default=False, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    workflow = relationship("TicketWorkflow", back_populates="statuses")
    tickets = relationship("Ticket", back_populates="status")


class TicketTransition(Base):
    __tablename__ = "ticket_transitions"

    id = Column(Integer, primary_key=True, index=True)
    workflow_id = Column(Integer, ForeignKey("ticket_workflows.id"), nullable=False, index=True)

    name = Column(String, nullable=False)
    from_status_id = Column(Integer, ForeignKey("ticket_statuses.id"), nullable=True)  # null = from any status
    to_status_id = Column(Integer, ForeignKey("ticket_statuses.id"), nullable=False)

    # conditions: {"only_assignee": true, "required_fields": ["resolution"]}
    conditions = Column(JSONB, nullable=True)
    # screen_fields: [{"field": "comment", "label": "Comment", "required": true}, ...]
    screen_fields = Column(JSONB, nullable=True)
    # post_actions: {"assign_to": {"type": "role"|"user"|"reporter"|"none", "value": ...}, "notify_watchers": true}
    post_actions = Column(JSONB, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    workflow = relationship("TicketWorkflow", back_populates="transitions")
    from_status = relationship("TicketStatus", foreign_keys=[from_status_id])
    to_status = relationship("TicketStatus", foreign_keys=[to_status_id])
