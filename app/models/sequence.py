from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Boolean
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from datetime import datetime
from app.core.database import Base


class Sequence(Base):
    __tablename__ = "sequences"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, index=True)
    description = Column(Text, nullable=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    status = Column(String, default="draft", nullable=False, index=True)  # draft, active, paused, archived
    goal = Column(String, nullable=True)
    tags = Column(JSONB, default=list)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    steps = relationship("SequenceStep", back_populates="sequence", order_by="SequenceStep.step_order", cascade="all, delete-orphan")
    enrollments = relationship("SequenceEnrollment", back_populates="sequence", cascade="all, delete-orphan")
    created_by = relationship("User", foreign_keys=[created_by_user_id])


class SequenceStep(Base):
    __tablename__ = "sequence_steps"

    id = Column(Integer, primary_key=True, index=True)
    sequence_id = Column(Integer, ForeignKey("sequences.id"), nullable=False, index=True)
    step_order = Column(Integer, nullable=False)
    step_type = Column(String, default="email", nullable=False)  # email, sms, whatsapp, task, wait
    template_id = Column(Integer, ForeignKey("templates.id"), nullable=True)
    delay_days = Column(Integer, default=0, nullable=False)
    delay_hours = Column(Integer, default=0, nullable=False)
    subject = Column(String, nullable=True)
    body = Column(Text, nullable=True)
    condition = Column(String, default="always", nullable=False)  # always, if_not_opened, if_not_clicked, if_not_replied
    task_note = Column(Text, nullable=True)

    sequence = relationship("Sequence", back_populates="steps")
    template = relationship("Template")


class SequenceEnrollment(Base):
    __tablename__ = "sequence_enrollments"

    id = Column(Integer, primary_key=True, index=True)
    sequence_id = Column(Integer, ForeignKey("sequences.id"), nullable=False, index=True)
    contact_id = Column(Integer, ForeignKey("contacts.id"), nullable=False, index=True)
    status = Column(String, default="active", nullable=False, index=True)  # active, paused, completed, unsubscribed, failed
    current_step = Column(Integer, default=0, nullable=False)
    enrolled_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    next_send_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    enrolled_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    sequence = relationship("Sequence", back_populates="enrollments")
    contact = relationship("Contact")
    enrolled_by = relationship("User", foreign_keys=[enrolled_by_user_id])
    logs = relationship("SequenceStepLog", back_populates="enrollment", cascade="all, delete-orphan")


class SequenceStepLog(Base):
    __tablename__ = "sequence_step_logs"

    id = Column(Integer, primary_key=True, index=True)
    enrollment_id = Column(Integer, ForeignKey("sequence_enrollments.id"), nullable=False, index=True)
    step_id = Column(Integer, ForeignKey("sequence_steps.id"), nullable=False)
    status = Column(String, default="pending", nullable=False)  # pending, sent, skipped, failed
    sent_at = Column(DateTime, nullable=True)
    error = Column(Text, nullable=True)

    enrollment = relationship("SequenceEnrollment", back_populates="logs")
    step = relationship("SequenceStep")
