from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, DECIMAL, Enum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from datetime import datetime
import enum
from app.core.database import Base


class DealStatus(str, enum.Enum):
    OPEN = "open"
    WON = "won"
    LOST = "lost"


class Deal(Base):
    __tablename__ = "deals"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)

    title = Column(String, nullable=False, index=True)
    amount = Column(DECIMAL(15, 2), nullable=True)
    currency = Column(String(3), nullable=False, default="USD")
    status = Column(Enum(DealStatus), default=DealStatus.OPEN, nullable=False, index=True)

    pipeline_id = Column(Integer, ForeignKey("pipelines.id"), nullable=False, index=True)
    stage_id = Column(Integer, ForeignKey("deal_stages.id"), nullable=False, index=True)

    contact_id = Column(Integer, ForeignKey("contacts.id"), nullable=True, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    expected_close_date = Column(DateTime, nullable=True)
    actual_close_date = Column(DateTime, nullable=True)
    won_reason = Column(String, nullable=True)
    lost_reason = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    custom_fields = Column(JSONB, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    pipeline = relationship("Pipeline", back_populates="deals")
    stage = relationship("DealStage", back_populates="deals")
    contact = relationship("Contact", back_populates="deals")
    account = relationship("Account", back_populates="deals")
    owner = relationship("User", back_populates="owned_deals")
    company = relationship("Company", back_populates="deals")


from app.models.contact import Contact
from app.models.account import Account
from app.models.user import User
from app.models.company import Company

Contact.deals = relationship("Deal", back_populates="contact")
Account.deals = relationship("Deal", back_populates="account")
User.owned_deals = relationship("Deal", back_populates="owner")
Company.deals = relationship("Deal", back_populates="company")
