from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Text
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

    # Stripe integration fields
    stripe_price_id = Column(String, nullable=True, index=True)
    stripe_product_id = Column(String, nullable=True, index=True)

    # User limit and trial configuration
    default_user_limit = Column(Integer, default=5, nullable=False)
    trial_days = Column(Integer, default=14, nullable=False)

    # Plan description and billing interval
    description = Column(Text, nullable=True)
    billing_interval = Column(String, default="month")  # month or year

    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    # Relationships
    users = relationship("User", back_populates="subscription_plan")
    company_subscriptions = relationship("CompanySubscription", back_populates="subscription_plan")
