"""Billing API Endpoints for Stripe subscription management and On-Premise licensing."""

from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, get_current_active_user, require_super_admin
from app.core.config import settings

# Stripe is optional (only needed for cloud mode)
try:
    import stripe
    STRIPE_AVAILABLE = True
except ImportError:
    stripe = None
    STRIPE_AVAILABLE = False
from app.models.user import User
from app.schemas.subscription_plan import SubscriptionPlan
from app.schemas.company_subscription import (
    SubscriptionStatus,
    UserLimitUpdate,
    CheckoutSessionCreate,
    CheckoutSessionResponse,
    PortalSessionResponse,
)
from app.schemas.license import (
    LicenseActivationRequest,
    LicenseActivationResponse,
    LicenseGenerateRequest,
    LicenseGenerateResponse,
    LicenseStatusResponse,
)
from app.services import subscription_service, company_subscription_service, license_service

router = APIRouter()

# Configure Stripe API key (only if available)
if STRIPE_AVAILABLE and stripe:
    stripe.api_key = settings.STRIPE_SECRET_KEY
stripe_webhook_secret = settings.STRIPE_WEBHOOK_SECRET


@router.get("/plans", response_model=list[SubscriptionPlan])
def get_subscription_plans(db: Session = Depends(get_db)):
    """
    Fetch all available subscription plans.
    Returns only active plans.
    """
    plans = subscription_service.get_subscription_plans(db)
    return [p for p in plans if p.is_active]


@router.get("/status", response_model=SubscriptionStatus)
def get_billing_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Get the current subscription status for the user's company.
    Includes trial info, user limits, and billing period.
    """
    if not current_user.company_id:
        raise HTTPException(status_code=400, detail="User is not associated with a company")

    return company_subscription_service.get_subscription_status(db, current_user.company_id)


@router.post("/create-checkout-session", response_model=CheckoutSessionResponse)
async def create_checkout_session(
    checkout_data: CheckoutSessionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """
    Create a Stripe Checkout session for a given plan.
    Returns the checkout URL to redirect the user to.
    """
    if not STRIPE_AVAILABLE:
        raise HTTPException(
            status_code=501,
            detail="Stripe is not available. This endpoint is only available in cloud mode."
        )

    plan = subscription_service.get_subscription_plan(db, checkout_data.plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")

    if not plan.stripe_price_id:
        raise HTTPException(status_code=400, detail="Plan is not configured for Stripe billing")

    if not current_user.company_id:
        raise HTTPException(status_code=400, detail="User is not associated with a company")

    # Get existing subscription to check for Stripe customer ID
    existing_subscription = company_subscription_service.get_subscription_by_company_id(
        db, current_user.company_id
    )

    try:
        checkout_params = {
            "line_items": [
                {
                    "price": plan.stripe_price_id,
                    "quantity": 1,
                },
            ],
            "mode": "subscription",
            "success_url": f"{settings.FRONTEND_URL}/billing?success=true&session_id={{CHECKOUT_SESSION_ID}}",
            "cancel_url": f"{settings.FRONTEND_URL}/billing?canceled=true",
            "metadata": {
                "company_id": str(current_user.company_id),
                "user_id": str(current_user.id),
                "plan_id": str(plan.id),
            },
            "subscription_data": {
                "metadata": {
                    "company_id": str(current_user.company_id),
                    "plan_id": str(plan.id),
                }
            }
        }

        # If customer already exists, use their Stripe customer ID
        if existing_subscription and existing_subscription.stripe_customer_id:
            checkout_params["customer"] = existing_subscription.stripe_customer_id
        else:
            # Create or associate customer during checkout
            checkout_params["customer_email"] = current_user.email

        checkout_session = stripe.checkout.Session.create(**checkout_params)

        return CheckoutSessionResponse(
            url=checkout_session.url,
            session_id=checkout_session.id
        )

    except stripe.error.StripeError as e:
        raise HTTPException(status_code=500, detail=f"Stripe error: {str(e)}")


@router.post("/create-portal-session", response_model=PortalSessionResponse)
async def create_portal_session(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """
    Create a Stripe Customer Portal session.
    Allows customers to manage their subscription, update payment methods, etc.
    """
    if not STRIPE_AVAILABLE:
        raise HTTPException(
            status_code=501,
            detail="Stripe is not available. This endpoint is only available in cloud mode."
        )

    if not current_user.company_id:
        raise HTTPException(status_code=400, detail="User is not associated with a company")

    subscription = company_subscription_service.get_subscription_by_company_id(
        db, current_user.company_id
    )

    if not subscription or not subscription.stripe_customer_id:
        raise HTTPException(
            status_code=400,
            detail="No active subscription found. Please subscribe to a plan first."
        )

    try:
        portal_session = stripe.billing_portal.Session.create(
            customer=subscription.stripe_customer_id,
            return_url=f"{settings.FRONTEND_URL}/billing",
        )
        return PortalSessionResponse(url=portal_session.url)

    except stripe.error.StripeError as e:
        raise HTTPException(status_code=500, detail=f"Stripe error: {str(e)}")


@router.post("/webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Handle webhooks from Stripe.
    Processes subscription lifecycle events.
    """
    if not STRIPE_AVAILABLE:
        raise HTTPException(
            status_code=501,
            detail="Stripe is not available."
        )

    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, stripe_webhook_secret
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    event_type = event["type"]
    data_object = event["data"]["object"]

    # Handle checkout.session.completed - New subscription created
    if event_type == "checkout.session.completed":
        await handle_checkout_completed(db, data_object)

    # Handle invoice.paid - Successful payment (initial or renewal)
    elif event_type == "invoice.paid":
        await handle_invoice_paid(db, data_object)

    # Handle invoice.payment_failed - Failed payment
    elif event_type == "invoice.payment_failed":
        await handle_payment_failed(db, data_object)

    # Handle customer.subscription.updated - Subscription changes
    elif event_type == "customer.subscription.updated":
        await handle_subscription_updated(db, data_object)

    # Handle customer.subscription.deleted - Subscription canceled
    elif event_type == "customer.subscription.deleted":
        await handle_subscription_deleted(db, data_object)

    return {"status": "success"}


async def handle_checkout_completed(db: Session, session: dict):
    """Handle checkout.session.completed event."""
    metadata = session.get("metadata", {})
    company_id = metadata.get("company_id")
    plan_id = metadata.get("plan_id")

    if not company_id or not plan_id:
        print(f"Missing metadata in checkout session: {session.get('id')}")
        return

    company_id = int(company_id)
    plan_id = int(plan_id)

    # Get subscription details from Stripe
    stripe_subscription_id = session.get("subscription")
    stripe_customer_id = session.get("customer")

    if stripe_subscription_id:
        # Fetch the subscription to get period dates
        stripe_sub = stripe.Subscription.retrieve(stripe_subscription_id)

        company_subscription_service.activate_subscription(
            db=db,
            company_id=company_id,
            stripe_customer_id=stripe_customer_id,
            stripe_subscription_id=stripe_subscription_id,
            subscription_plan_id=plan_id,
            current_period_start=datetime.fromtimestamp(stripe_sub.current_period_start),
            current_period_end=datetime.fromtimestamp(stripe_sub.current_period_end),
        )
        print(f"Activated subscription for company {company_id}")


async def handle_invoice_paid(db: Session, invoice: dict):
    """Handle invoice.paid event - renewal success."""
    stripe_subscription_id = invoice.get("subscription")

    if not stripe_subscription_id:
        return

    # Get the subscription to find period dates
    stripe_sub = stripe.Subscription.retrieve(stripe_subscription_id)

    company_subscription_service.handle_subscription_renewed(
        db=db,
        stripe_subscription_id=stripe_subscription_id,
        current_period_start=datetime.fromtimestamp(stripe_sub.current_period_start),
        current_period_end=datetime.fromtimestamp(stripe_sub.current_period_end),
    )
    print(f"Renewed subscription {stripe_subscription_id}")


async def handle_payment_failed(db: Session, invoice: dict):
    """Handle invoice.payment_failed event."""
    stripe_subscription_id = invoice.get("subscription")

    if not stripe_subscription_id:
        return

    company_subscription_service.handle_payment_failed(
        db=db,
        stripe_subscription_id=stripe_subscription_id,
    )
    print(f"Payment failed for subscription {stripe_subscription_id}")


async def handle_subscription_updated(db: Session, subscription: dict):
    """Handle customer.subscription.updated event."""
    stripe_subscription_id = subscription.get("id")
    cancel_at_period_end = subscription.get("cancel_at_period_end", False)

    if not stripe_subscription_id:
        return

    db_subscription = company_subscription_service.get_subscription_by_stripe_subscription_id(
        db, stripe_subscription_id
    )

    if db_subscription:
        db_subscription.cancel_at_period_end = cancel_at_period_end

        # Update period dates
        if subscription.get("current_period_start") and subscription.get("current_period_end"):
            db_subscription.current_period_start = datetime.fromtimestamp(
                subscription["current_period_start"]
            )
            db_subscription.current_period_end = datetime.fromtimestamp(
                subscription["current_period_end"]
            )

        db_subscription.updated_at = datetime.utcnow()
        db.commit()
        print(f"Updated subscription {stripe_subscription_id}")


async def handle_subscription_deleted(db: Session, subscription: dict):
    """Handle customer.subscription.deleted event - full cancellation."""
    stripe_subscription_id = subscription.get("id")

    if not stripe_subscription_id:
        return

    company_subscription_service.handle_subscription_canceled(
        db=db,
        stripe_subscription_id=stripe_subscription_id,
        cancel_at_period_end=False,
    )
    print(f"Canceled subscription {stripe_subscription_id}")


# Admin endpoints

@router.put("/admin/companies/{company_id}/user-limit", dependencies=[Depends(require_super_admin)])
def update_company_user_limit(
    company_id: int,
    update_data: UserLimitUpdate,
    db: Session = Depends(get_db),
):
    """
    Admin endpoint to update a company's user limit.
    Requires super admin privileges.
    """
    try:
        subscription = company_subscription_service.update_user_limit(
            db=db,
            company_id=company_id,
            new_limit=update_data.user_limit,
        )
        return {
            "success": True,
            "company_id": company_id,
            "new_user_limit": subscription.user_limit,
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ========== License Endpoints (On-Premise) ==========


@router.get("/licenses/status", response_model=LicenseStatusResponse)
def get_license_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """
    Get the current license status.
    Works in both cloud and on-premise modes.
    """
    return license_service.get_license_status(db)


@router.post("/licenses/activate", response_model=LicenseActivationResponse)
def activate_license(
    request: LicenseActivationRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin),
):
    """
    Activate a license key for on-premise deployment.
    Requires super admin privileges.
    """
    if settings.DEPLOYMENT_MODE != "on_premise":
        raise HTTPException(
            status_code=400,
            detail="License activation is only available in on-premise mode."
        )

    success, message, payload = license_service.activate_license(db, request.license_key)

    if not success:
        raise HTTPException(status_code=400, detail=message)

    return LicenseActivationResponse(
        success=True,
        message=message,
        status=license_service.get_license_status(db),
    )


@router.post("/licenses/generate", response_model=LicenseGenerateResponse)
def generate_license(
    request: LicenseGenerateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin),
):
    """
    Generate a new license key.
    Requires super admin privileges.
    This is typically used by the license authority to create licenses.
    """
    if not settings.LICENSE_KEY_SECRET:
        raise HTTPException(
            status_code=500,
            detail="LICENSE_KEY_SECRET is not configured. Cannot generate licenses."
        )

    try:
        license_key, payload = license_service.generate_license_key(
            instance_name=request.instance_name,
            max_users=request.max_users,
            max_companies=request.max_companies,
            features=request.features,
            expires_in_days=request.expires_in_days,
        )

        return LicenseGenerateResponse(
            license_key=license_key,
            payload=payload,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate license: {str(e)}")
