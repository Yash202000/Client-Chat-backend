from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from datetime import datetime
from app.core.database import Base


class ContactActivity(Base):
    __tablename__ = "contact_activities"

    id = Column(Integer, primary_key=True, index=True)
    contact_id = Column(Integer, ForeignKey("contacts.id"), nullable=False, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)

    # Activity type: note, email_sent, email_opened, call, meeting, sequence_enrolled,
    # sequence_step, campaign_sent, deal_created, lead_created, task, custom
    activity_type = Column(String(50), nullable=False, index=True)

    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)

    # Optional link to a related entity
    entity_type = Column(String(50), nullable=True)   # deal, campaign, sequence, lead
    entity_id = Column(Integer, nullable=True)

    # Who performed/logged the activity (nullable for automated events)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    # Arbitrary extra data
    extra_data = Column(JSONB, nullable=True)

    occurred_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    contact = relationship("Contact", back_populates="activities")
    company = relationship("Company", back_populates="contact_activities")
    user = relationship("User", back_populates="contact_activities")
