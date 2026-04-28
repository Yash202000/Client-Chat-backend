from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey, JSON
from sqlalchemy.sql import func
from app.core.database import Base


class CalendarEvent(Base):
    __tablename__ = "calendar_events"

    id                  = Column(Integer, primary_key=True, index=True)
    company_id          = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    user_id             = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    title               = Column(String(255), nullable=False)
    event_type          = Column(String(50), default="meeting")   # meeting|task|call|out-of-office|reminder
    start_time          = Column(DateTime(timezone=True), nullable=False)
    end_time            = Column(DateTime(timezone=True), nullable=False)
    is_all_day          = Column(Boolean, default=False, nullable=False)
    location            = Column(String(500), nullable=True)
    description         = Column(Text, nullable=True)
    attendees           = Column(JSON, default=list)              # list of email strings
    livekit_room_name   = Column(String(255), nullable=True)      # set when event has a video meeting
    recurrence_rule     = Column(String(50), nullable=True)       # daily|weekly|monthly
    recurrence_interval = Column(Integer, default=1, nullable=True)
    recurrence_end_date = Column(DateTime(timezone=True), nullable=True)
    parent_event_id     = Column(Integer, ForeignKey("calendar_events.id", ondelete="SET NULL"), nullable=True)
    channel_id          = Column(Integer, ForeignKey("chat_channels.id", ondelete="SET NULL"), nullable=True)
    created_at          = Column(DateTime(timezone=True), server_default=func.now())
    updated_at          = Column(DateTime(timezone=True), onupdate=func.now())
