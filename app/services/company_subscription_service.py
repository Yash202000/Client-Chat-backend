"""Company Subscription Service for managing company-level subscriptions.

Supports dual deployment modes:
- Cloud (Stripe): Per-company subscription management
- On-Premise (License): Instance-wide license validation
"""

from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.company_subscription import CompanySubscription
from app.models.subscription_plan import SubscriptionPlan
from app.models.user import User
from app.schemas.company_subscription import (
    CompanySubscriptionCreate,
    CompanySubscriptionUpdate,
    SubscriptionStatus,
)


def get_subscription_by_company_id(db: Session, company_id: int) -> Optional[CompanySubscription]:
    """Get subscription for a company."""
    return db.query(CompanySubscription).filter(
        CompanySubscription.company_id == company_id
    ).first()


def get_subscription_by_razorpay_customer_id(db: Session, razorpay_customer_id: str) -> Optional[CompanySubscription]:
    """Get subscription by Razorpay customer ID."""
    return db.query(CompanySubscription).filter(
        CompanySubscription.razorpay_customer_id == razorpay_customer_id
    ).first()


def get_subscription_by_razorpay_subscription_id(db: Session, razorpay_subscription_id: str) -> Optional[CompanySubscription]:
    """Get subscription by Razorpay subscription ID."""
    return db.query(CompanySubscription).filter(
        CompanySubscription.razorpay_subscription_id == razorpay_subscription_id
    ).first()


def create_trial_subscription(
    db: Session,
    company_id: int,
    subscription_plan_id: Optional[int] = None,
    trial_days: int = 14,
    user_limit: int = 5
) -> CompanySubscription:
    """
    Create a trial subscription for a new company.
    Called when a company is created during signup.
    """
    now = datetime.utcnow()
    trial_end = now + timedelta(days=trial_days)

    # If a plan is provided, get its default user limit
    if subscription_plan_id:
        plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.id == subscription_plan_id).first()
        if plan:
            user_limit = plan.default_user_limit
            trial_days = plan.trial_days

    subscription = CompanySubscription(
        company_id=company_id,
        subscription_plan_id=subscription_plan_id,
        status="trial",
        trial_start_date=now,
        trial_end_date=trial_end,
        user_limit=user_limit,
        cancel_at_period_end=False,
    )
    db.add(subscription)
    db.commit()
    db.refresh(subscription)
    return subscription


def activate_subscription(
    db: Session,
    company_id: int,
    razorpay_customer_id: str,
    razorpay_subscription_id: str,
    subscription_plan_id: int,
    current_period_start: datetime,
    current_period_end: datetime,
) -> CompanySubscription:
    """
    Activate a subscription after successful payment.
    Updates the company subscription with Razorpay details and sets status to active.
    """
    subscription = get_subscription_by_company_id(db, company_id)

    if not subscription:
        # Create new subscription if it doesn't exist
        subscription = CompanySubscription(
            company_id=company_id,
            subscription_plan_id=subscription_plan_id,
            razorpay_customer_id=razorpay_customer_id,
            razorpay_subscription_id=razorpay_subscription_id,
            status="active",
            current_period_start=current_period_start,
            current_period_end=current_period_end,
            user_limit=5,
        )
        db.add(subscription)
    else:
        # Update existing subscription
        subscription.razorpay_customer_id = razorpay_customer_id
        subscription.razorpay_subscription_id = razorpay_subscription_id
        subscription.subscription_plan_id = subscription_plan_id
        subscription.status = "active"
        subscription.current_period_start = current_period_start
        subscription.current_period_end = current_period_end
        subscription.updated_at = datetime.utcnow()

    # Get the plan to set user limit
    plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.id == subscription_plan_id).first()
    if plan:
        subscription.user_limit = plan.default_user_limit

    db.commit()
    db.refresh(subscription)
    return subscription


def update_subscription(
    db: Session,
    subscription: CompanySubscription,
    update_data: CompanySubscriptionUpdate
) -> CompanySubscription:
    """Update subscription with provided data."""
    update_dict = update_data.model_dump(exclude_unset=True)
    for field, value in update_dict.items():
        setattr(subscription, field, value)
    subscription.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(subscription)
    return subscription


def can_add_user(db: Session, company_id: int) -> bool:
    """
    Check if the company can add more users based on their subscription limit.
    Returns True if under the limit, False if at or over the limit.

    In on-premise mode, checks the instance-wide license limit instead.
    """
    # On-premise mode: check instance-wide license
    if settings.DEPLOYMENT_MODE == "on_premise":
        from app.services import license_service
        return license_service.can_add_user_on_premise(db)

    # Cloud mode: check per-company subscription
    subscription = get_subscription_by_company_id(db, company_id)

    # If no subscription exists, default to allowing (for backwards compatibility)
    if not subscription:
        return True

    # Check subscription status
    if subscription.status in ["canceled", "expired"]:
        return False

    # Check if trial has expired
    if subscription.status == "trial" and subscription.trial_end_date:
        if datetime.utcnow() > subscription.trial_end_date:
            return False

    current_count = get_user_count(db, company_id)
    return current_count < subscription.user_limit


def get_user_count(db: Session, company_id: int) -> int:
    """Count active users in a company."""
    return db.query(User).filter(
        User.company_id == company_id,
        User.is_active == True
    ).count()


def get_subscription_status(db: Session, company_id: int) -> SubscriptionStatus:
    """
    Get full subscription status for the frontend.
    Includes plan details, trial info, and user limit info.
    """
    subscription = get_subscription_by_company_id(db, company_id)
    current_user_count = get_user_count(db, company_id)

    if not subscription:
        # No subscription - return default trial-like status
        return SubscriptionStatus(
            plan_name=None,
            plan_id=None,
            status="trial",
            is_trial=True,
            trial_days_remaining=14,
            current_period_start=None,
            current_period_end=None,
            user_limit=5,
            current_user_count=current_user_count,
            users_remaining=5 - current_user_count,
            cancel_at_period_end=False,
            razorpay_customer_id=None,
        )

    # Calculate trial days remaining
    trial_days_remaining = None
    is_trial = subscription.status == "trial"
    if is_trial and subscription.trial_end_date:
        remaining = subscription.trial_end_date - datetime.utcnow()
        trial_days_remaining = max(0, remaining.days)

    # Get plan name
    plan_name = None
    plan_id = None
    if subscription.subscription_plan:
        plan_name = subscription.subscription_plan.name
        plan_id = subscription.subscription_plan.id

    return SubscriptionStatus(
        plan_name=plan_name,
        plan_id=plan_id,
        status=subscription.status,
        is_trial=is_trial,
        trial_days_remaining=trial_days_remaining,
        current_period_start=subscription.current_period_start,
        current_period_end=subscription.current_period_end,
        user_limit=subscription.user_limit,
        current_user_count=current_user_count,
        users_remaining=max(0, subscription.user_limit - current_user_count),
        cancel_at_period_end=subscription.cancel_at_period_end or False,
        razorpay_customer_id=subscription.razorpay_customer_id,
    )


def update_user_limit(db: Session, company_id: int, new_limit: int) -> CompanySubscription:
    """Admin function to update user limit for a company."""
    subscription = get_subscription_by_company_id(db, company_id)

    if not subscription:
        raise ValueError(f"No subscription found for company {company_id}")

    subscription.user_limit = new_limit
    subscription.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(subscription)
    return subscription


def handle_subscription_renewed(
    db: Session,
    razorpay_subscription_id: str,
    current_period_start: datetime,
    current_period_end: datetime,
) -> Optional[CompanySubscription]:
    """
    Handle subscription renewal from Razorpay webhook.
    Updates the billing period dates.
    """
    subscription = get_subscription_by_razorpay_subscription_id(db, razorpay_subscription_id)

    if not subscription:
        return None

    subscription.status = "active"
    subscription.current_period_start = current_period_start
    subscription.current_period_end = current_period_end
    subscription.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(subscription)
    return subscription


def handle_subscription_canceled(
    db: Session,
    razorpay_subscription_id: str,
    cancel_at_period_end: bool = False,
) -> Optional[CompanySubscription]:
    """
    Handle subscription cancellation from Razorpay webhook.
    If cancel_at_period_end is True, just mark it as scheduled for cancellation.
    Otherwise, mark as canceled immediately.
    """
    subscription = get_subscription_by_razorpay_subscription_id(db, razorpay_subscription_id)

    if not subscription:
        return None

    if cancel_at_period_end:
        subscription.cancel_at_period_end = True
    else:
        subscription.status = "canceled"
        subscription.cancel_at_period_end = False

    subscription.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(subscription)
    return subscription


def handle_payment_failed(
    db: Session,
    razorpay_subscription_id: str,
) -> Optional[CompanySubscription]:
    """
    Handle failed payment from Razorpay webhook.
    Marks the subscription as past_due.
    """
    subscription = get_subscription_by_razorpay_subscription_id(db, razorpay_subscription_id)

    if not subscription:
        return None

    subscription.status = "past_due"
    subscription.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(subscription)
    return subscription


def check_and_expire_trials(db: Session) -> int:
    """
    Background task to expire trials that have ended.
    Returns the number of subscriptions expired.
    """
    now = datetime.utcnow()
    expired_trials = db.query(CompanySubscription).filter(
        CompanySubscription.status == "trial",
        CompanySubscription.trial_end_date < now
    ).all()

    count = 0
    for subscription in expired_trials:
        subscription.status = "expired"
        subscription.updated_at = now
        count += 1

    if count > 0:
        db.commit()

    return count


def is_subscription_active(db: Session, company_id: int) -> bool:
    """
    Check if a company has an active subscription.
    Returns True for active or trial (not expired) subscriptions.

    In on-premise mode, checks the instance-wide license validity instead.
    """
    # On-premise mode: check instance-wide license
    if settings.DEPLOYMENT_MODE == "on_premise":
        from app.services import license_service

        # First check env var license
        if settings.LICENSE_KEY:
            return license_service.is_license_valid(settings.LICENSE_KEY)

        # Then check database license
        instance_license = license_service.get_instance_license(db)
        if instance_license and instance_license.license_key:
            return license_service.is_license_valid(instance_license.license_key)

        return False

    # Cloud mode: check per-company subscription
    subscription = get_subscription_by_company_id(db, company_id)

    if not subscription:
        return False

    # Active subscription
    if subscription.status == "active":
        return True

    # Valid trial
    if subscription.status == "trial" and subscription.trial_end_date:
        return datetime.utcnow() <= subscription.trial_end_date

    return False
