from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime, Boolean
from sqlalchemy.orm import relationship
from datetime import datetime
from app.core.database import Base


class TicketIssueType(Base):
    __tablename__ = "ticket_issue_types"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)

    name = Column(String, nullable=False)      # Bug, Task, Story, Epic, Sub-task
    icon = Column(String, nullable=True)       # lucide icon name
    color = Column(String(7), nullable=False, default="#6366f1")
    description = Column(Text, nullable=True)
    is_default = Column(Boolean, default=False, nullable=False)
    position = Column(Integer, default=0, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    company = relationship("Company", back_populates="ticket_issue_types")
    tickets = relationship("Ticket", back_populates="issue_type")
