from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Boolean
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from datetime import datetime
from app.core.database import Base


class CaptureForm(Base):
    __tablename__ = "capture_forms"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, index=True)
    description = Column(Text, nullable=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    slug = Column(String, nullable=False, unique=True, index=True)
    status = Column(String, default="active", nullable=False)  # active, paused, archived
    fields = Column(JSONB, default=list, nullable=False)  # list of field definitions
    settings = Column(JSONB, default=dict, nullable=False)  # submit_message, redirect_url, notify_email, etc.
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    submissions = relationship("FormSubmission", back_populates="form", cascade="all, delete-orphan")
    created_by = relationship("User", foreign_keys=[created_by_user_id])


class FormSubmission(Base):
    __tablename__ = "form_submissions"

    id = Column(Integer, primary_key=True, index=True)
    form_id = Column(Integer, ForeignKey("capture_forms.id"), nullable=False, index=True)
    data = Column(JSONB, nullable=False)  # { field_key: value, ... }
    contact_id = Column(Integer, ForeignKey("contacts.id"), nullable=True, index=True)
    ip_address = Column(String, nullable=True)
    submitted_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    form = relationship("CaptureForm", back_populates="submissions")
    contact = relationship("Contact")
