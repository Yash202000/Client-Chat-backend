from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Text, BigInteger
from sqlalchemy.orm import relationship
from app.core.database import Base
import datetime

class SubscriptionPlan(Base):
    __tablename__ = "subscription_plans"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False)
    price = Column(Float, nullable=False)
    currency = Column(String, default="USD")
    features = Column(String, nullable=True)  # JSON string or comma-separated list of features
    is_active = Column(Boolean, default=True)

    # Razorpay integration fields
    razorpay_plan_id = Column(String, nullable=True, index=True)

    # User limit and trial configuration
    default_user_limit = Column(Integer, default=5, nullable=False)
    trial_days = Column(Integer, default=14, nullable=False)

    # User limit enforcement
    warn_threshold = Column(Integer, nullable=True)       # show warning banner at this count
    addon_seat_cap = Column(Integer, default=0, nullable=False)  # max purchasable addon seats (0 = none)
    addon_seat_price_usd = Column(Float, nullable=True)   # price per addon seat in USD
    addon_seat_price_inr = Column(Float, nullable=True)   # price per addon seat in INR
    grace_period_days = Column(Integer, default=0, nullable=False)  # days of grace after exceeding cap

    # Agent limits (None = unlimited)
    max_agents = Column(Integer, nullable=True)            # total agents allowed
    max_active_agents = Column(Integer, nullable=True)     # published/deployed agents allowed
    max_monthly_conversations = Column(Integer, nullable=True)  # AI conversation turns per month
    max_kb_upload_bytes = Column(Integer, nullable=True)   # max bytes per KB file upload
    max_knowledge_bases = Column(Integer, nullable=True)   # total knowledge bases allowed
    max_channels = Column(Integer, nullable=True)          # total internal chat channels allowed
    max_contacts = Column(Integer, nullable=True)
    max_leads = Column(Integer, nullable=True)
    max_workflows = Column(Integer, nullable=True)
    max_campaigns = Column(Integer, nullable=True)
    max_monthly_emails = Column(Integer, nullable=True)
    max_storage_bytes = Column(BigInteger, nullable=True)

    # Plan description and billing interval
    description = Column(Text, nullable=True)
    billing_interval = Column(String, default="month")  # month or year

    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    # Relationships
    users = relationship("User", back_populates="subscription_plan")
    company_subscriptions = relationship("CompanySubscription", back_populates="subscription_plan")
