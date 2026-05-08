from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime, Enum
from sqlalchemy.orm import relationship
from datetime import datetime
import enum
from app.core.database import Base


class SprintStatus(str, enum.Enum):
    FUTURE = "future"
    ACTIVE = "active"
    COMPLETED = "completed"


class TicketSprint(Base):
    __tablename__ = "ticket_sprints"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    project_id = Column(Integer, ForeignKey("ticket_projects.id", ondelete="CASCADE"), nullable=False, index=True)

    name = Column(String, nullable=False)
    goal = Column(Text, nullable=True)
    status = Column(Enum(SprintStatus), default=SprintStatus.FUTURE, nullable=False, index=True)

    start_date = Column(DateTime, nullable=True)
    end_date = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    company = relationship("Company", back_populates="ticket_sprints")
    project = relationship("TicketProject", back_populates="sprints")
    tickets = relationship("Ticket", back_populates="sprint")
