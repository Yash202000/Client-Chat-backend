"""Company Subscription Model for company-level billing and user limits."""

from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from app.core.database import Base
import datetime


class CompanySubscription(Base):
    """
    Represents a company's subscription to a plan.
    Each company has one subscription that tracks:
    - Stripe billing information
    - Subscription status (trial, active, past_due, canceled, expired)
    - User limits
    - Billing period dates
    """
    __tablename__ = "company_subscriptions"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), unique=True, nullable=False)
    subscription_plan_id = Column(Integer, ForeignKey("subscription_plans.id"), nullable=True)

    # Stripe identifiers
    stripe_customer_id = Column(String, nullable=True, index=True)
    stripe_subscription_id = Column(String, nullable=True, index=True)

    # Subscription status: trial, active, past_due, canceled, expired
    status = Column(String, default="trial", nullable=False)

    # Trial period
    trial_start_date = Column(DateTime, nullable=True)
    trial_end_date = Column(DateTime, nullable=True)

    # Current billing period
    current_period_start = Column(DateTime, nullable=True)
    current_period_end = Column(DateTime, nullable=True)

    # User limit for the company (can be customized per company)
    user_limit = Column(Integer, default=5, nullable=False)

    # Whether the subscription is scheduled to cancel at period end
    cancel_at_period_end = Column(Boolean, default=False)

    # Timestamps
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    # Relationships
    company = relationship("Company", back_populates="subscription")
    subscription_plan = relationship("SubscriptionPlan", back_populates="company_subscriptions")
