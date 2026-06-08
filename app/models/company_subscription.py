"""Company Subscription Model for company-level billing and user limits."""

from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, BigInteger
from sqlalchemy.orm import relationship
from app.core.database import Base
import datetime


class CompanySubscription(Base):
    """
    Represents a company's subscription to a plan.
    Each company has one subscription that tracks:
    - Razorpay billing information
    - Subscription status (trial, active, past_due, canceled, expired)
    - User limits
    - Billing period dates
    """
    __tablename__ = "company_subscriptions"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), unique=True, nullable=False)
    subscription_plan_id = Column(Integer, ForeignKey("subscription_plans.id"), nullable=True)

    # Razorpay identifiers
    razorpay_customer_id = Column(String, nullable=True, index=True)
    razorpay_subscription_id = Column(String, nullable=True, index=True)

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

    # Addon seats purchased on top of the plan limit (Growth only)
    addon_seats = Column(Integer, default=0, nullable=False)

    # Grace period end date — set when company exceeds limit due to plan downgrade
    grace_period_end = Column(DateTime, nullable=True)

    # Monthly conversation tracking (reset on the 1st of each month)
    monthly_conversation_count = Column(Integer, default=0, nullable=False)
    conversation_count_reset_at = Column(DateTime, nullable=True)

    # Monthly email tracking and storage quota
    monthly_email_count = Column(Integer, default=0, nullable=False)
    email_count_reset_at = Column(DateTime, nullable=True)
    total_storage_bytes = Column(BigInteger, default=0, nullable=False)

    # Whether the subscription is scheduled to cancel at period end
    cancel_at_period_end = Column(Boolean, default=False)

    # Trial lifecycle email flags (day 0, 7, 12, expiry)
    trial_welcome_sent = Column(Boolean, default=False, nullable=False)
    trial_day7_sent = Column(Boolean, default=False, nullable=False)
    trial_day12_sent = Column(Boolean, default=False, nullable=False)
    trial_expiry_sent = Column(Boolean, default=False, nullable=False)

    # Dunning email flags for payment failure sequences
    dunning_attempt_1_sent = Column(Boolean, default=False, nullable=False)
    dunning_attempt_2_sent = Column(Boolean, default=False, nullable=False)
    dunning_attempt_3_sent = Column(Boolean, default=False, nullable=False)
    last_dunning_sent_at = Column(DateTime, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    # Relationships
    company = relationship("Company", back_populates="subscription")
    subscription_plan = relationship("SubscriptionPlan", back_populates="company_subscriptions")
