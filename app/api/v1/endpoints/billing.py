"""Billing API Endpoints for Razorpay subscription management and On-Premise licensing."""

import hmac
import hashlib
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, get_current_active_user, require_super_admin
from app.core.config import settings

# Razorpay is optional (only needed for cloud mode)
try:
    import razorpay
    RAZORPAY_AVAILABLE = True
except ImportError:
    razorpay = None
    RAZORPAY_AVAILABLE = False

from app.models.user import User
from app.schemas.subscription_plan import SubscriptionPlan
from app.schemas.company_subscription import (
    SubscriptionStatus,
    UserLimitUpdate,
    SubscriptionCreateRequest,
    SubscriptionCreateResponse,
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

# Configure Razorpay client (only if available)
razorpay_client = None
if RAZORPAY_AVAILABLE and razorpay and settings.RAZORPAY_KEY_ID and settings.RAZORPAY_KEY_SECRET:
    razorpay_client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))


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


@router.post("/create-subscription", response_model=SubscriptionCreateResponse)
async def create_subscription(
    subscription_data: SubscriptionCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """
    Create a Razorpay subscription for a given plan.
    Returns subscription details for Razorpay checkout.
    """
    if not RAZORPAY_AVAILABLE or not razorpay_client:
        raise HTTPException(
            status_code=501,
            detail="Razorpay is not available. This endpoint is only available in cloud mode."
        )

    plan = subscription_service.get_subscription_plan(db, subscription_data.plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")

    if not plan.razorpay_plan_id:
        raise HTTPException(status_code=400, detail="Plan is not configured for Razorpay billing")

    if not current_user.company_id:
        raise HTTPException(status_code=400, detail="User is not associated with a company")

    # Get existing subscription to check for Razorpay customer ID
    existing_subscription = company_subscription_service.get_subscription_by_company_id(
        db, current_user.company_id
    )

    try:
        customer_id = None

        # If customer already exists in our database, use their Razorpay customer ID
        if existing_subscription and existing_subscription.razorpay_customer_id:
            customer_id = existing_subscription.razorpay_customer_id
        else:
            # Create a new customer in Razorpay
            # Build full name from first_name and last_name, fallback to email
            full_name = None
            if current_user.first_name and current_user.last_name:
                full_name = f"{current_user.first_name} {current_user.last_name}"
            elif current_user.first_name:
                full_name = current_user.first_name
            elif current_user.last_name:
                full_name = current_user.last_name

            customer_data = {
                "name": full_name or current_user.email,
                "email": current_user.email,
                "notes": {
                    "company_id": str(current_user.company_id),
                    "user_id": str(current_user.id),
                }
            }

            try:
                customer = razorpay_client.customer.create(data=customer_data)
                customer_id = customer['id']
            except Exception as customer_error:
                # If customer already exists, fetch by email
                if "already exists" in str(customer_error).lower():
                    # Fetch all customers and find by email
                    customers = razorpay_client.customer.all()
                    for cust in customers.get('items', []):
                        if cust.get('email') == current_user.email:
                            customer_id = cust['id']
                            break

                    if not customer_id:
                        raise HTTPException(
                            status_code=500,
                            detail="Customer exists in Razorpay but couldn't be retrieved. Please contact support."
                        )
                else:
                    raise customer_error

            # Save customer_id to database immediately to prevent duplicate creation on retry
            if existing_subscription and not existing_subscription.razorpay_customer_id:
                company_subscription_service.update_subscription(
                    db=db,
                    subscription=existing_subscription,
                    update_data={"razorpay_customer_id": customer_id}
                )

        # Create subscription in Razorpay
        subscription_payload = {
            "plan_id": plan.razorpay_plan_id,
            "customer_id": customer_id,
            "total_count": 120,  # Max billing cycles (10 years for monthly)
            "quantity": 1,
            "customer_notify": 1,
            "notes": {
                "company_id": str(current_user.company_id),
                "user_id": str(current_user.id),
                "plan_id": str(plan.id),
            }
        }

        razorpay_subscription = razorpay_client.subscription.create(data=subscription_payload)

        return SubscriptionCreateResponse(
            subscription_id=razorpay_subscription['id'],
            razorpay_key_id=settings.RAZORPAY_KEY_ID,
            plan_id=plan.razorpay_plan_id,
            plan_name=plan.name,
            amount=int(plan.price * 100),  # Razorpay expects amount in paise
            currency=plan.currency or "INR",
            customer_id=customer_id,
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Razorpay error: {str(e)}")


@router.post("/verify-payment")
async def verify_payment(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """
    Verify Razorpay payment after successful checkout.
    Called by frontend after Razorpay checkout success callback.
    """
    if not RAZORPAY_AVAILABLE or not razorpay_client:
        raise HTTPException(
            status_code=501,
            detail="Razorpay is not available."
        )

    body = await request.json()
    razorpay_payment_id = body.get("razorpay_payment_id")
    razorpay_subscription_id = body.get("razorpay_subscription_id")
    razorpay_signature = body.get("razorpay_signature")
    plan_id = body.get("plan_id")

    if not all([razorpay_payment_id, razorpay_subscription_id, razorpay_signature]):
        raise HTTPException(status_code=400, detail="Missing payment verification parameters")

    try:
        # Verify the payment signature
        params_dict = {
            'razorpay_payment_id': razorpay_payment_id,
            'razorpay_subscription_id': razorpay_subscription_id,
            'razorpay_signature': razorpay_signature
        }
        razorpay_client.utility.verify_subscription_payment_signature(params_dict)

        # Get subscription details from Razorpay
        razorpay_sub = razorpay_client.subscription.fetch(razorpay_subscription_id)

        # Calculate period dates
        current_period_start = datetime.utcnow()
        # Get billing interval from plan
        plan = subscription_service.get_subscription_plan(db, int(plan_id)) if plan_id else None
        if plan and plan.billing_interval == "year":
            current_period_end = current_period_start + timedelta(days=365)
        else:
            current_period_end = current_period_start + timedelta(days=30)

        # Activate subscription in database
        company_subscription_service.activate_subscription(
            db=db,
            company_id=current_user.company_id,
            razorpay_customer_id=razorpay_sub.get('customer_id'),
            razorpay_subscription_id=razorpay_subscription_id,
            subscription_plan_id=int(plan_id) if plan_id else None,
            current_period_start=current_period_start,
            current_period_end=current_period_end,
        )

        return {"status": "success", "message": "Payment verified and subscription activated"}

    except razorpay.errors.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid payment signature")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Verification error: {str(e)}")


@router.post("/webhook")
async def razorpay_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Handle webhooks from Razorpay.
    Processes subscription lifecycle events.
    """
    if not RAZORPAY_AVAILABLE:
        raise HTTPException(
            status_code=501,
            detail="Razorpay is not available."
        )

    payload = await request.body()
    signature = request.headers.get("X-Razorpay-Signature")

    # Verify webhook signature
    if settings.RAZORPAY_WEBHOOK_SECRET:
        expected_signature = hmac.new(
            settings.RAZORPAY_WEBHOOK_SECRET.encode('utf-8'),
            payload,
            hashlib.sha256
        ).hexdigest()

        if signature != expected_signature:
            raise HTTPException(status_code=400, detail="Invalid webhook signature")

    try:
        import json
        event = json.loads(payload)
    except:
        raise HTTPException(status_code=400, detail="Invalid payload")

    event_type = event.get("event")
    payload_data = event.get("payload", {})

    # Handle subscription.activated - Subscription activated
    if event_type == "subscription.activated":
        await handle_subscription_activated(db, payload_data)

    # Handle subscription.charged - Successful payment
    elif event_type == "subscription.charged":
        await handle_subscription_charged(db, payload_data)

    # Handle subscription.pending - Payment pending
    elif event_type == "subscription.pending":
        await handle_subscription_pending(db, payload_data)

    # Handle subscription.halted - Payment failed multiple times
    elif event_type == "subscription.halted":
        await handle_subscription_halted(db, payload_data)

    # Handle subscription.cancelled - Subscription cancelled
    elif event_type == "subscription.cancelled":
        await handle_subscription_cancelled(db, payload_data)

    # Handle subscription.completed - Subscription completed all cycles
    elif event_type == "subscription.completed":
        await handle_subscription_completed(db, payload_data)

    # Handle payment.failed
    elif event_type == "payment.failed":
        await handle_payment_failed(db, payload_data)

    return {"status": "success"}


async def handle_subscription_activated(db: Session, payload: dict):
    """Handle subscription.activated event."""
    subscription = payload.get("subscription", {}).get("entity", {})
    razorpay_subscription_id = subscription.get("id")
    customer_id = subscription.get("customer_id")
    notes = subscription.get("notes", {})

    company_id = notes.get("company_id")
    plan_id = notes.get("plan_id")

    if not company_id:
        return

    company_id = int(company_id)
    plan_id = int(plan_id) if plan_id else None

    current_period_start = datetime.utcnow()
    current_period_end = current_period_start + timedelta(days=30)

    if subscription.get("current_end"):
        current_period_end = datetime.fromtimestamp(subscription["current_end"])
    if subscription.get("current_start"):
        current_period_start = datetime.fromtimestamp(subscription["current_start"])

    company_subscription_service.activate_subscription(
        db=db,
        company_id=company_id,
        razorpay_customer_id=customer_id,
        razorpay_subscription_id=razorpay_subscription_id,
        subscription_plan_id=plan_id,
        current_period_start=current_period_start,
        current_period_end=current_period_end,
    )


async def handle_subscription_charged(db: Session, payload: dict):
    """Handle subscription.charged event - renewal success."""
    subscription = payload.get("subscription", {}).get("entity", {})
    razorpay_subscription_id = subscription.get("id")

    if not razorpay_subscription_id:
        return

    current_period_start = datetime.utcnow()
    current_period_end = current_period_start + timedelta(days=30)

    if subscription.get("current_end"):
        current_period_end = datetime.fromtimestamp(subscription["current_end"])
    if subscription.get("current_start"):
        current_period_start = datetime.fromtimestamp(subscription["current_start"])

    company_subscription_service.handle_subscription_renewed(
        db=db,
        razorpay_subscription_id=razorpay_subscription_id,
        current_period_start=current_period_start,
        current_period_end=current_period_end,
    )


async def handle_subscription_pending(db: Session, payload: dict):
    """Handle subscription.pending event - payment pending."""
    subscription = payload.get("subscription", {}).get("entity", {})
    razorpay_subscription_id = subscription.get("id")

    if not razorpay_subscription_id:
        return

    # Mark as past_due when payment is pending
    db_subscription = company_subscription_service.get_subscription_by_razorpay_subscription_id(
        db, razorpay_subscription_id
    )
    if db_subscription:
        db_subscription.status = "past_due"
        db_subscription.updated_at = datetime.utcnow()
        db.commit()


async def handle_subscription_halted(db: Session, payload: dict):
    """Handle subscription.halted event - payment failed multiple times."""
    subscription = payload.get("subscription", {}).get("entity", {})
    razorpay_subscription_id = subscription.get("id")

    if not razorpay_subscription_id:
        return

    company_subscription_service.handle_payment_failed(
        db=db,
        razorpay_subscription_id=razorpay_subscription_id,
    )


async def handle_subscription_cancelled(db: Session, payload: dict):
    """Handle subscription.cancelled event."""
    subscription = payload.get("subscription", {}).get("entity", {})
    razorpay_subscription_id = subscription.get("id")

    if not razorpay_subscription_id:
        return

    company_subscription_service.handle_subscription_canceled(
        db=db,
        razorpay_subscription_id=razorpay_subscription_id,
        cancel_at_period_end=False,
    )


async def handle_subscription_completed(db: Session, payload: dict):
    """Handle subscription.completed event - all billing cycles completed."""
    subscription = payload.get("subscription", {}).get("entity", {})
    razorpay_subscription_id = subscription.get("id")

    if not razorpay_subscription_id:
        return

    company_subscription_service.handle_subscription_canceled(
        db=db,
        razorpay_subscription_id=razorpay_subscription_id,
        cancel_at_period_end=False,
    )


async def handle_payment_failed(db: Session, payload: dict):
    """Handle payment.failed event."""
    payment = payload.get("payment", {}).get("entity", {})
    notes = payment.get("notes", {})

    # Try to get subscription_id from payment notes or subscription entity
    subscription_id = notes.get("razorpay_subscription_id")

    if not subscription_id:
        return

    company_subscription_service.handle_payment_failed(
        db=db,
        razorpay_subscription_id=subscription_id,
    )


@router.post("/cancel-subscription")
async def cancel_subscription(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """
    Cancel the current subscription.
    """
    if not RAZORPAY_AVAILABLE or not razorpay_client:
        raise HTTPException(
            status_code=501,
            detail="Razorpay is not available."
        )

    if not current_user.company_id:
        raise HTTPException(status_code=400, detail="User is not associated with a company")

    subscription = company_subscription_service.get_subscription_by_company_id(
        db, current_user.company_id
    )

    if not subscription or not subscription.razorpay_subscription_id:
        raise HTTPException(
            status_code=400,
            detail="No active subscription found."
        )

    try:
        # Cancel subscription in Razorpay (at end of current billing cycle)
        razorpay_client.subscription.cancel(
            subscription.razorpay_subscription_id,
            {"cancel_at_cycle_end": 1}
        )

        # Mark in database
        subscription.cancel_at_period_end = True
        subscription.updated_at = datetime.utcnow()
        db.commit()

        return {"status": "success", "message": "Subscription will be cancelled at the end of the billing period"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to cancel subscription: {str(e)}")


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
