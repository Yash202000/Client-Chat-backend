from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey, Enum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from datetime import datetime
import enum
from app.core.database import Base


class BookingSlotStatus(str, enum.Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"


class BookingLink(Base):
    """
    A public, shareable scheduling link (Calendly-style).
    Availability is stored as JSONB keyed by lowercase day name.

    availability example:
    {
      "monday":    [{"start": "09:00", "end": "17:00"}],
      "tuesday":   [{"start": "09:00", "end": "17:00"}],
      "wednesday": [{"start": "09:00", "end": "12:00"}, {"start": "14:00", "end": "17:00"}],
      "thursday":  [{"start": "09:00", "end": "17:00"}],
      "friday":    [{"start": "09:00", "end": "17:00"}],
      "saturday":  [],
      "sunday":    []
    }
    """
    __tablename__ = "booking_links"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    slug = Column(String(100), unique=True, nullable=False, index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    location = Column(String(500), nullable=True)   # "Zoom", "Google Meet", address, etc.

    duration_minutes = Column(Integer, nullable=False, default=30)
    buffer_before_minutes = Column(Integer, nullable=False, default=0)
    buffer_after_minutes = Column(Integer, nullable=False, default=0)

    availability = Column(JSONB, nullable=False, default=dict)
    # date_overrides: {"YYYY-MM-DD": [{"start": "HH:MM", "end": "HH:MM"}]}
    # empty list  = date is blocked; list with windows = custom hours for that date
    date_overrides = Column(JSONB, nullable=True, default=dict)
    timezone = Column(String(64), nullable=False, default="UTC")

    max_advance_days = Column(Integer, nullable=False, default=60)   # how far ahead bookers can schedule
    min_notice_hours = Column(Integer, nullable=False, default=1)    # minimum advance notice

    color = Column(String(7), nullable=True, default="#6366f1")
    is_active = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    owner = relationship("User", back_populates="booking_links")
    slots = relationship("BookingSlot", back_populates="booking_link", cascade="all, delete-orphan")


class BookingSlot(Base):
    """A confirmed booking made via a BookingLink."""
    __tablename__ = "booking_slots"

    id = Column(Integer, primary_key=True, index=True)
    booking_link_id = Column(Integer, ForeignKey("booking_links.id"), nullable=False, index=True)
    calendar_event_id = Column(Integer, ForeignKey("calendar_events.id"), nullable=True, index=True)

    # Booker info (may or may not be a Contact in the system)
    booker_name = Column(String(255), nullable=False)
    booker_email = Column(String(255), nullable=False, index=True)
    booker_phone = Column(String(50), nullable=True)
    booker_notes = Column(Text, nullable=True)

    start_time = Column(DateTime, nullable=False, index=True)
    end_time = Column(DateTime, nullable=False)

    status = Column(Enum(BookingSlotStatus), nullable=False, default=BookingSlotStatus.CONFIRMED)

    # Link to CRM contact if matched/created
    contact_id = Column(Integer, ForeignKey("contacts.id"), nullable=True, index=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    booking_link = relationship("BookingLink", back_populates="slots")
    contact = relationship("Contact")


# Back-populate on User
from app.models.user import User
User.booking_links = relationship("BookingLink", back_populates="owner")
