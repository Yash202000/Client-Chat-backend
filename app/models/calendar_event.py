from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, JSON
from sqlalchemy.sql import func
from app.core.database import Base


class CalendarEvent(Base):
    __tablename__ = "calendar_events"

    id          = Column(Integer, primary_key=True, index=True)
    company_id  = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    user_id     = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    title       = Column(String(255), nullable=False)
    event_type  = Column(String(50), default="meeting")   # meeting|task|call|out-of-office|reminder
    start_time  = Column(DateTime(timezone=True), nullable=False)
    end_time    = Column(DateTime(timezone=True), nullable=False)
    description = Column(Text, nullable=True)
    attendees   = Column(JSON, default=list)              # list of email strings
    created_at  = Column(DateTime(timezone=True), server_default=func.now())
    updated_at  = Column(DateTime(timezone=True), onupdate=func.now())
