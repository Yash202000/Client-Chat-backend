from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from datetime import datetime
from app.core.database import Base


class TicketProject(Base):
    __tablename__ = "ticket_projects"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    name = Column(String, nullable=False, index=True)
    key = Column(String(10), nullable=False, index=True)  # e.g. "PROJ"
    description = Column(Text, nullable=True)
    icon = Column(String, nullable=True)
    color = Column(String(7), nullable=True, default="#6366f1")

    default_workflow_id = Column(Integer, ForeignKey("ticket_workflows.id"), nullable=True)
    ticket_counter = Column(Integer, default=0, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    company = relationship("Company", back_populates="ticket_projects")
    created_by = relationship("User", foreign_keys=[created_by_id])
    default_workflow = relationship("TicketWorkflow", foreign_keys=[default_workflow_id])
    tickets = relationship("Ticket", back_populates="project", cascade="all, delete-orphan")
    members = relationship("TicketProjectMember", back_populates="project", cascade="all, delete-orphan")
    sprints = relationship("TicketSprint", back_populates="project", cascade="all, delete-orphan",
                           order_by="TicketSprint.created_at")
