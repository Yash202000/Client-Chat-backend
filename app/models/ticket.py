from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime, Boolean, Enum, Table, Float
from sqlalchemy.dialects.postgresql import JSONB, ARRAY
from sqlalchemy.orm import relationship
from datetime import datetime
import enum
from app.core.database import Base


class TicketPriority(str, enum.Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NONE = "none"


class TicketLinkType(str, enum.Enum):
    BLOCKS = "blocks"
    IS_BLOCKED_BY = "is_blocked_by"
    DUPLICATES = "duplicates"
    IS_DUPLICATED_BY = "is_duplicated_by"
    RELATES_TO = "relates_to"
    CLONES = "clones"


class TicketActivityAction(str, enum.Enum):
    CREATED = "created"
    UPDATED = "updated"
    TRANSITIONED = "transitioned"
    COMMENTED = "commented"
    ASSIGNED = "assigned"
    ATTACHMENT_ADDED = "attachment_added"
    ATTACHMENT_REMOVED = "attachment_removed"
    LINKED = "linked"
    UNLINKED = "unlinked"
    WATCHER_ADDED = "watcher_added"


ticket_watchers = Table(
    "ticket_watchers",
    Base.metadata,
    Column("ticket_id", Integer, ForeignKey("tickets.id", ondelete="CASCADE"), primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
)

ticket_co_assignees = Table(
    "ticket_co_assignees",
    Base.metadata,
    Column("ticket_id", Integer, ForeignKey("tickets.id", ondelete="CASCADE"), primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
)


class Ticket(Base):
    __tablename__ = "tickets"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    project_id = Column(Integer, ForeignKey("ticket_projects.id"), nullable=False, index=True)

    ticket_number = Column(String, nullable=False, index=True)  # e.g. "PROJ-42"

    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)

    issue_type_id = Column(Integer, ForeignKey("ticket_issue_types.id"), nullable=True)
    status_id = Column(Integer, ForeignKey("ticket_statuses.id"), nullable=True, index=True)
    priority = Column(Enum(TicketPriority, values_callable=lambda obj: [e.value for e in obj]), default=TicketPriority.MEDIUM, nullable=False, index=True)

    assignee_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    reporter_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    parent_id = Column(Integer, ForeignKey("tickets.id"), nullable=True, index=True)
    sprint_id = Column(Integer, ForeignKey("ticket_sprints.id"), nullable=True, index=True)

    labels = Column(JSONB, nullable=True)   # list of strings

    due_date = Column(DateTime, nullable=True)
    start_date = Column(DateTime, nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    closed_at = Column(DateTime, nullable=True)

    story_points = Column(Float, nullable=True)
    time_estimate = Column(Integer, nullable=True)   # minutes
    time_spent = Column(Integer, nullable=True)       # minutes

    # CRM links
    contact_id = Column(Integer, ForeignKey("contacts.id"), nullable=True, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True, index=True)
    deal_id = Column(Integer, ForeignKey("deals.id"), nullable=True, index=True)

    custom_fields = Column(JSONB, nullable=True)
    position = Column(Float, default=0.0, nullable=False)  # for board ordering

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    company = relationship("Company", back_populates="tickets")
    project = relationship("TicketProject", back_populates="tickets")
    sprint = relationship("TicketSprint", back_populates="tickets", foreign_keys=[sprint_id])
    issue_type = relationship("TicketIssueType", back_populates="tickets")
    status = relationship("TicketStatus", back_populates="tickets")
    assignee = relationship("User", foreign_keys=[assignee_id])
    reporter = relationship("User", foreign_keys=[reporter_id])
    parent = relationship("Ticket", remote_side=[id], foreign_keys=[parent_id])
    sub_tickets = relationship("Ticket", foreign_keys=[parent_id])
    contact = relationship("Contact", foreign_keys=[contact_id])
    account = relationship("Account", foreign_keys=[account_id])
    deal = relationship("Deal", foreign_keys=[deal_id])
    comments = relationship("TicketComment", back_populates="ticket",
                            cascade="all, delete-orphan", order_by="TicketComment.created_at")
    attachments = relationship("TicketAttachment", back_populates="ticket",
                               cascade="all, delete-orphan")
    activities = relationship("TicketActivity", back_populates="ticket",
                              cascade="all, delete-orphan", order_by="TicketActivity.created_at.desc()")
    watchers = relationship("User", secondary=ticket_watchers)
    co_assignees = relationship("User", secondary=ticket_co_assignees)
    source_links = relationship("TicketLink", foreign_keys="TicketLink.source_ticket_id",
                                cascade="all, delete-orphan")
    target_links = relationship("TicketLink", foreign_keys="TicketLink.target_ticket_id",
                                cascade="all, delete-orphan")


class TicketComment(Base):
    __tablename__ = "ticket_comments"

    id = Column(Integer, primary_key=True, index=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True)
    author_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    parent_id = Column(Integer, ForeignKey("ticket_comments.id"), nullable=True)

    body = Column(Text, nullable=False)
    is_internal = Column(Boolean, default=False, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    ticket = relationship("Ticket", back_populates="comments")
    author = relationship("User", foreign_keys=[author_id])
    replies = relationship("TicketComment", foreign_keys=[parent_id])


class TicketAttachment(Base):
    __tablename__ = "ticket_attachments"

    id = Column(Integer, primary_key=True, index=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True)
    uploaded_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    file_name = Column(String, nullable=False)
    file_size = Column(Integer, nullable=True)   # bytes
    mime_type = Column(String, nullable=True)
    file_url = Column(String, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    ticket = relationship("Ticket", back_populates="attachments")
    uploaded_by = relationship("User", foreign_keys=[uploaded_by_id])


class TicketActivity(Base):
    __tablename__ = "ticket_activities"

    id = Column(Integer, primary_key=True, index=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True)
    actor_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    action = Column(Enum(TicketActivityAction, values_callable=lambda obj: [e.value for e in obj]), nullable=False)
    field_name = Column(String, nullable=True)
    old_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=True)
    metadata_ = Column("metadata", JSONB, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    ticket = relationship("Ticket", back_populates="activities")
    actor = relationship("User", foreign_keys=[actor_id])


class TicketLink(Base):
    __tablename__ = "ticket_links"

    id = Column(Integer, primary_key=True, index=True)
    source_ticket_id = Column(Integer, ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True)
    target_ticket_id = Column(Integer, ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True)
    link_type = Column(Enum(TicketLinkType, values_callable=lambda obj: [e.value for e in obj]), nullable=False)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    source_ticket = relationship("Ticket", foreign_keys=[source_ticket_id])
    target_ticket = relationship("Ticket", foreign_keys=[target_ticket_id])
    created_by = relationship("User", foreign_keys=[created_by_id])


class TicketProjectMember(Base):
    __tablename__ = "ticket_project_members"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("ticket_projects.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String, default="member", nullable=False)  # viewer, member, admin

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    project = relationship("TicketProject", back_populates="members")
    user = relationship("User", foreign_keys=[user_id])
