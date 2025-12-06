from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Enum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from datetime import datetime
import enum
from app.core.database import Base


class NoteType(str, enum.Enum):
    """Types of notes/activities that can be logged"""
    NOTE = "note"  # General note
    CALL = "call"  # Phone call log
    MEETING = "meeting"  # Meeting log
    EMAIL = "email"  # Email log
    TASK = "task"  # Task/follow-up


class EntityNote(Base):
    """
    Notes and activity logs for Contacts and Leads.
    Polymorphic - can be attached to either a Contact OR a Lead.
    """
    __tablename__ = "entity_notes"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)

    # Polymorphic: attach to contact OR lead (one must be set)
    contact_id = Column(Integer, ForeignKey("contacts.id"), nullable=True, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id"), nullable=True, index=True)

    # Note content
    note_type = Column(Enum(NoteType), nullable=False, default=NoteType.NOTE, index=True)
    title = Column(String(255), nullable=True)  # Optional title for calls/meetings
    content = Column(Text, nullable=False)

    # Activity metadata (for calls/meetings)
    activity_date = Column(DateTime, nullable=True)  # When the call/meeting happened
    duration_minutes = Column(Integer, nullable=True)  # Call/meeting duration
    participants = Column(JSONB, nullable=True)  # List of participant names/emails
    outcome = Column(String(255), nullable=True)  # e.g., "Scheduled follow-up", "Converted"

    # Audit fields
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    contact = relationship("Contact", back_populates="notes")
    lead = relationship("Lead", back_populates="notes_list")
    creator = relationship("User", back_populates="created_notes")
    company = relationship("Company", back_populates="entity_notes")


# Add back-population to related models
from app.models.contact import Contact
from app.models.lead import Lead
from app.models.user import User
from app.models.company import Company

Contact.notes = relationship("EntityNote", back_populates="contact", cascade="all, delete-orphan", order_by=EntityNote.created_at.desc())
Lead.notes_list = relationship("EntityNote", back_populates="lead", cascade="all, delete-orphan", order_by=EntityNote.created_at.desc())
User.created_notes = relationship("EntityNote", back_populates="creator")
Company.entity_notes = relationship("EntityNote", back_populates="company", cascade="all, delete-orphan")
