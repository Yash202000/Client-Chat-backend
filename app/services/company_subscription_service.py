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
    update_dict = update_data if isinstance(update_data, dict) else update_data.model_dump(exclude_unset=True)
    for field, value in update_dict.items():
        setattr(subscription, field, value)
    subscription.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(subscription)
    return subscription


def can_add_user(db: Session, company_id: int) -> bool:
    """
    Check if the company can add more users based on their subscription limit.
    Returns True if under the effective cap (user_limit + addon_seats), False otherwise.

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

    # Check grace period — existing users can work but new invites are blocked
    if subscription.grace_period_end and datetime.utcnow() <= subscription.grace_period_end:
        return False

    current_count = get_user_count(db, company_id)
    effective_limit = subscription.user_limit + (subscription.addon_seats or 0)
    return current_count < effective_limit


def get_user_count(db: Session, company_id: int) -> int:
    """Count active users in a company."""
    return db.query(User).filter(
        User.company_id == company_id,
        User.is_active == True
    ).count()


def get_company_features(db: Session, company_id: int) -> list[str]:
    """Return the list of feature keys available to a company based on their plan.

    Returns ["all"] for active trials and plans whose features field contains "all".
    Returns [] for expired/canceled subscriptions.
    """
    subscription = get_subscription_by_company_id(db, company_id)

    if not subscription:
        return ["all"]

    # Expired/canceled — no features
    if subscription.status in ("canceled", "expired"):
        return []

    # Active trial — access scoped to the trial plan's features
    if subscription.status == "trial":
        if subscription.trial_end_date and datetime.utcnow() > subscription.trial_end_date:
            return []
        # If trial is tied to a specific plan, respect that plan's feature list
        if subscription.subscription_plan and subscription.subscription_plan.features:
            raw = subscription.subscription_plan.features
            parts = [f.strip() for f in raw.split(",") if f.strip()]
            return parts
        # Generic trial with no plan assigned (e.g. Free Trial) — full access
        return ["all"]

    # Active/past_due subscription — derive from plan
    if subscription.subscription_plan and subscription.subscription_plan.features:
        raw = subscription.subscription_plan.features
        parts = [f.strip() for f in raw.split(",") if f.strip()]
        return parts  # may contain "all" if plan uses that shorthand

    # Active subscription with no plan features defined — grant full access
    return ["all"]


def get_subscription_status(db: Session, company_id: int) -> SubscriptionStatus:
    """
    Get full subscription status for the frontend.
    Includes plan details, trial info, and user limit info.
    """
    subscription = get_subscription_by_company_id(db, company_id)
    current_user_count = get_user_count(db, company_id)

    if not subscription:
        # No subscription record — auto-create a trial so the countdown is real
        subscription = create_trial_subscription(db, company_id)

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

    addon_seats = subscription.addon_seats or 0
    effective_limit = subscription.user_limit + addon_seats

    # Plan-level seat addon and warn threshold
    plan = subscription.subscription_plan
    addon_seat_cap = plan.addon_seat_cap if plan else 0
    addon_seat_price_usd = plan.addon_seat_price_usd if plan else None
    addon_seat_price_inr = plan.addon_seat_price_inr if plan else None
    warn_threshold = plan.warn_threshold if plan else None
    users_near_limit = (
        warn_threshold is not None
        and current_user_count >= warn_threshold
        and current_user_count < effective_limit
    )

    monthly_email_count = subscription.monthly_email_count or 0
    max_monthly_emails = plan.max_monthly_emails if plan else None
    total_storage_bytes = subscription.total_storage_bytes or 0
    max_storage_bytes = plan.max_storage_bytes if plan else None

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
        users_remaining=max(0, effective_limit - current_user_count),
        addon_seats=addon_seats,
        addon_seat_cap=addon_seat_cap or 0,
        addon_seat_price_usd=addon_seat_price_usd,
        addon_seat_price_inr=addon_seat_price_inr,
        warn_threshold=warn_threshold,
        users_near_limit=users_near_limit,
        grace_period_end=subscription.grace_period_end,
        monthly_conversation_count=subscription.monthly_conversation_count or 0,
        max_monthly_conversations=plan.max_monthly_conversations if plan else None,
        conversations_near_limit=(
            plan is not None
            and plan.max_monthly_conversations is not None
            and (subscription.monthly_conversation_count or 0) >= plan.max_monthly_conversations * 0.8
        ),
        monthly_email_count=monthly_email_count,
        max_monthly_emails=max_monthly_emails,
        emails_near_limit=(
            max_monthly_emails is not None
            and monthly_email_count >= max_monthly_emails * 0.8
        ),
        total_storage_bytes=total_storage_bytes,
        max_storage_bytes=max_storage_bytes,
        storage_near_limit=(
            max_storage_bytes is not None
            and total_storage_bytes >= max_storage_bytes * 0.85
        ),
        cancel_at_period_end=subscription.cancel_at_period_end or False,
        razorpay_customer_id=subscription.razorpay_customer_id,
        plan_features=get_company_features(db, company_id),
    )


def get_plan_limits(db: Session, company_id: int) -> dict:
    """Return the plan limits for a company — agents, conversations, KB upload size, KB count, channels, CRM."""
    subscription = get_subscription_by_company_id(db, company_id)
    if not subscription or not subscription.subscription_plan:
        return {"max_agents": None, "max_active_agents": None,
                "max_monthly_conversations": None, "max_kb_upload_bytes": None,
                "max_knowledge_bases": None, "max_channels": None,
                "max_contacts": None, "max_leads": None,
                "max_workflows": None, "max_campaigns": None,
                "max_monthly_emails": None, "max_storage_bytes": None}
    plan = subscription.subscription_plan
    return {
        "max_agents": plan.max_agents,
        "max_active_agents": plan.max_active_agents,
        "max_monthly_conversations": plan.max_monthly_conversations,
        "max_kb_upload_bytes": plan.max_kb_upload_bytes,
        "max_knowledge_bases": plan.max_knowledge_bases,
        "max_channels": plan.max_channels,
        "max_contacts": plan.max_contacts,
        "max_leads": plan.max_leads,
        "max_workflows": plan.max_workflows,
        "max_campaigns": plan.max_campaigns,
        "max_monthly_emails": plan.max_monthly_emails,
        "max_storage_bytes": plan.max_storage_bytes,
    }


def can_create_agent(db: Session, company_id: int) -> tuple[bool, str]:
    """Check if the company can create another agent. Returns (allowed, reason)."""
    from app.models.agent import Agent
    limits = get_plan_limits(db, company_id)
    max_agents = limits["max_agents"]
    if max_agents is None:
        return True, ""
    current_count = db.query(Agent).filter(
        Agent.company_id == company_id,
        Agent.status != "archived"
    ).count()
    if current_count >= max_agents:
        return False, f"Your plan allows a maximum of {max_agents} agent{'s' if max_agents != 1 else ''}. Upgrade to create more."
    return True, ""


def can_publish_agent(db: Session, company_id: int, agent_id: int) -> tuple[bool, str]:
    """Check if the company can publish/activate another agent. Returns (allowed, reason)."""
    from app.models.published_widget_settings import PublishedWidgetSettings
    from app.models.agent import Agent
    limits = get_plan_limits(db, company_id)
    max_active = limits["max_active_agents"]
    if max_active is None:
        return True, ""
    # Count active published agents for this company (excluding the agent being published)
    active_count = db.query(PublishedWidgetSettings).join(
        Agent, Agent.id == PublishedWidgetSettings.agent_id
    ).filter(
        Agent.company_id == company_id,
        PublishedWidgetSettings.is_active == True,
        PublishedWidgetSettings.agent_id != agent_id
    ).count()
    if active_count >= max_active:
        return False, f"Your plan allows {max_active} active agent{'s' if max_active != 1 else ''} at a time. Deactivate one or upgrade to publish more."
    return True, ""


def can_create_knowledge_base(db: Session, company_id: int) -> tuple[bool, str]:
    """Check if the company can create another knowledge base based on plan limits."""
    from app.models.knowledge_base import KnowledgeBase
    limits = get_plan_limits(db, company_id)
    max_kbs = limits.get("max_knowledge_bases")
    if not max_kbs:
        return True, ""
    current_count = db.query(KnowledgeBase).filter(KnowledgeBase.company_id == company_id).count()
    if current_count >= max_kbs:
        return False, f"Your plan allows a maximum of {max_kbs} knowledge base{'s' if max_kbs != 1 else ''}. Please upgrade to add more."
    return True, ""


def can_create_channel(db: Session, company_id: int) -> tuple[bool, str]:
    """Check if the company can create another internal chat channel based on plan limits."""
    from app.models.chat_channel import ChatChannel
    limits = get_plan_limits(db, company_id)
    max_channels = limits.get("max_channels")
    if not max_channels:
        return True, ""
    current_count = db.query(ChatChannel).filter(ChatChannel.company_id == company_id).count()
    if current_count >= max_channels:
        return False, f"Your plan allows a maximum of {max_channels} channel{'s' if max_channels != 1 else ''}. Please upgrade to add more."
    return True, ""


def can_create_contact(db, company_id: int) -> tuple[bool, str]:
    from app.models.contact import Contact
    limits = get_plan_limits(db, company_id)
    max_val = limits.get("max_contacts")
    if not max_val:
        return True, ""
    count = db.query(Contact).filter(Contact.company_id == company_id).count()
    if count >= max_val:
        return False, f"Your plan allows a maximum of {max_val:,} contacts. Upgrade to add more."
    return True, ""


def can_create_lead(db, company_id: int) -> tuple[bool, str]:
    from app.models.lead import Lead
    limits = get_plan_limits(db, company_id)
    max_val = limits.get("max_leads")
    if not max_val:
        return True, ""
    count = db.query(Lead).filter(Lead.company_id == company_id).count()
    if count >= max_val:
        return False, f"Your plan allows a maximum of {max_val:,} leads. Upgrade to add more."
    return True, ""


def can_create_workflow(db, company_id: int) -> tuple[bool, str]:
    from app.models.workflow import Workflow
    limits = get_plan_limits(db, company_id)
    max_val = limits.get("max_workflows")
    if not max_val:
        return True, ""
    count = db.query(Workflow).filter(Workflow.company_id == company_id).count()
    if count >= max_val:
        return False, f"Your plan allows a maximum of {max_val} workflows. Upgrade to add more."
    return True, ""


def can_create_campaign(db, company_id: int) -> tuple[bool, str]:
    from app.models.campaign import Campaign
    limits = get_plan_limits(db, company_id)
    max_val = limits.get("max_campaigns")
    if not max_val:
        return True, ""
    count = db.query(Campaign).filter(Campaign.company_id == company_id).count()
    if count >= max_val:
        return False, f"Your plan allows a maximum of {max_val} campaigns. Upgrade to add more."
    return True, ""


def can_send_emails(db, company_id: int, count: int = 1) -> tuple[bool, str]:
    """Check and reserve email send quota. Returns (allowed, reason)."""
    from datetime import datetime
    limits = get_plan_limits(db, company_id)
    max_emails = limits.get("max_monthly_emails")
    if not max_emails:
        return True, ""

    sub = db.query(CompanySubscription).filter(
        CompanySubscription.company_id == company_id
    ).first()
    if not sub:
        return True, ""

    now = datetime.utcnow()
    # Reset monthly counter if new calendar month
    if sub.email_count_reset_at is None or (
        sub.email_count_reset_at.year != now.year or
        sub.email_count_reset_at.month != now.month
    ):
        sub.monthly_email_count = 0
        sub.email_count_reset_at = now
        db.commit()

    if sub.monthly_email_count + count > max_emails:
        return False, (
            f"Your plan allows {max_emails:,} emails per month. "
            f"You've used {sub.monthly_email_count:,}. Upgrade to send more."
        )
    sub.monthly_email_count += count
    db.commit()
    return True, ""


def can_upload_storage(db, company_id: int, new_bytes: int) -> tuple[bool, str]:
    """Check if adding new_bytes would exceed the workspace storage quota."""
    limits = get_plan_limits(db, company_id)
    max_bytes = limits.get("max_storage_bytes")
    if not max_bytes:
        return True, ""

    sub = db.query(CompanySubscription).filter(
        CompanySubscription.company_id == company_id
    ).first()
    if not sub:
        return True, ""

    if (sub.total_storage_bytes or 0) + new_bytes > max_bytes:
        used_gb = round((sub.total_storage_bytes or 0) / (1024**3), 2)
        max_gb = round(max_bytes / (1024**3), 1)
        return False, (
            f"Storage limit reached ({used_gb} GB of {max_gb} GB used). "
            f"Delete files or upgrade your plan."
        )
    return True, ""


def update_storage_usage(db, company_id: int, delta_bytes: int) -> None:
    """Increment (positive) or decrement (negative) workspace storage usage."""
    sub = db.query(CompanySubscription).filter(
        CompanySubscription.company_id == company_id
    ).first()
    if not sub:
        return
    current = sub.total_storage_bytes or 0
    sub.total_storage_bytes = max(0, current + delta_bytes)
    db.commit()


def increment_conversation_count(db: Session, company_id: int) -> tuple[bool, str]:
    """Increment the monthly conversation counter. Returns (allowed, reason).
    Returns False when the company has hit their monthly cap.
    """
    subscription = get_subscription_by_company_id(db, company_id)
    if not subscription:
        return True, ""

    plan = subscription.subscription_plan
    max_conv = plan.max_monthly_conversations if plan else None

    # Reset counter if we're in a new month
    now = datetime.utcnow()
    reset_at = subscription.conversation_count_reset_at
    if reset_at is None or reset_at.month != now.month or reset_at.year != now.year:
        subscription.monthly_conversation_count = 0
        subscription.conversation_count_reset_at = now
        db.commit()

    if max_conv is not None and subscription.monthly_conversation_count >= max_conv:
        return False, (
            f"Your plan's monthly limit of {max_conv:,} AI conversations has been reached. "
            "Upgrade your plan or wait until next month."
        )

    subscription.monthly_conversation_count += 1
    db.commit()
    return True, ""


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


def handle_subscription_halted(
    db: Session,
    razorpay_subscription_id: str,
) -> Optional[CompanySubscription]:
    """
    Handle subscription.halted event — Razorpay exhausted all payment retries.
    Cancel the subscription and fall back to the free/trial plan so the user
    retains read access rather than hitting a hard block.
    """
    subscription = get_subscription_by_razorpay_subscription_id(db, razorpay_subscription_id)
    if not subscription:
        return None

    # Find the lowest-priced active free plan to fall back to
    free_plan = (
        db.query(SubscriptionPlan)
        .filter(SubscriptionPlan.price == 0, SubscriptionPlan.is_active == True)
        .order_by(SubscriptionPlan.id.asc())
        .first()
    )

    subscription.status = "canceled"
    subscription.cancel_at_period_end = False
    subscription.razorpay_subscription_id = None
    if free_plan:
        subscription.plan_id = free_plan.id
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
