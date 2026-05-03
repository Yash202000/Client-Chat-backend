from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from datetime import datetime
from app.core.database import Base


class CampaignSequenceTrigger(Base):
    __tablename__ = "campaign_sequence_triggers"

    id = Column(Integer, primary_key=True, index=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), nullable=False, index=True)
    sequence_id = Column(Integer, ForeignKey("sequences.id"), nullable=False, index=True)

    # When to enroll
    trigger_condition = Column(String, nullable=False)
    # on_send        — enroll all campaign contacts immediately
    # on_completion  — enroll contacts who completed the campaign
    # if_opened      — opened at least one email
    # if_not_opened  — never opened (after campaign ends)
    # if_clicked     — clicked at least one link
    # if_not_clicked — never clicked
    # if_replied     — replied
    # if_not_replied — never replied

    delay_hours = Column(Integer, default=0, nullable=False)  # wait N hours after condition met
    is_active = Column(Boolean, default=True, nullable=False)
    last_fired_at = Column(DateTime, nullable=True)
    enrolled_count = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    campaign = relationship("Campaign")
    sequence = relationship("Sequence")
