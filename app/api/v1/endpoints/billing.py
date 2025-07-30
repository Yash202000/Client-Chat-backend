from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session
import stripe

from app.core.dependencies import get_db, get_current_user
from app.core.config import settings
from app.models.user import User
from app.schemas.subscription_plan import SubscriptionPlan
from app.services import subscription_service, company_service

router = APIRouter()

# Configure Stripe API key
stripe.api_key = settings.STRIPE_SECRET_KEY
stripe_webhook_secret = settings.STRIPE_WEBHOOK_SECRET

@router.get("/plans", response_model=list[SubscriptionPlan])
def get_subscription_plans(db: Session = Depends(get_db)):
    """
    Fetch all available subscription plans.
    """
    return subscription_service.get_all_plans(db)

@router.get("/status")
def get_billing_status(
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    """
    Get the current subscription status for the user's company.
    """
    company = company_service.get_company(db, company_id=current_user.company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    return {
        "plan": company.subscription_plan.name if company.subscription_plan else "Free",
        "status": company.subscription_status,
        "current_period_end": company.subscription_end_date,
    }

@router.post("/create-checkout-session")
async def create_checkout_session(
    plan_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Create a Stripe Checkout session for a given plan.
    """
    plan = subscription_service.get_plan(db, plan_id)
    if not plan or not plan.stripe_price_id:
        raise HTTPException(status_code=404, detail="Plan not found or not configured for Stripe.")

    try:
        checkout_session = stripe.checkout.Session.create(
            line_items=[
                {
                    "price": plan.stripe_price_id,
                    "quantity": 1,
                },
            ],
            mode="subscription",
            success_url=f"{settings.FRONTEND_URL}/billing?success=true",
            cancel_url=f"{settings.FRONTEND_URL}/billing?canceled=true",
            metadata={
                "company_id": current_user.company_id,
                "user_id": current_user.id,
                "plan_id": plan.id
            }
        )
        return {"url": checkout_session.url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/stripe-webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Handle webhooks from Stripe.
    """
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, stripe_webhook_secret
        )
    except ValueError as e:
        # Invalid payload
        raise HTTPException(status_code=400, detail=str(e))
    except stripe.error.SignatureVerificationError as e:
        # Invalid signature
        raise HTTPException(status_code=400, detail=str(e))

    # Handle the checkout.session.completed event
    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        company_id = int(session["metadata"]["company_id"])
        plan_id = int(session["metadata"]["plan_id"])
        
        # Update company subscription status in the database
        subscription_service.update_company_subscription(
            db,
            company_id=company_id,
            plan_id=plan_id,
            status="active" # or whatever status Stripe provides
        )
        print(f"Successfully updated subscription for company {company_id} to plan {plan_id}")

    return Response(status_code=200)
