from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from app.core.dependencies import get_db, get_current_active_user
from app.models import user as models_user
from app.models.company import Company
from app.models.company_subscription import CompanySubscription
from app.models.subscription_plan import SubscriptionPlan

router = APIRouter()

VALID_TEAM_SIZES = {"solo", "2-10", "11-50", "51-200", "200+"}
VALID_USE_CASES = {"customer_support", "sales", "marketing", "hr", "other"}


class OnboardingQualification(BaseModel):
    company_name: Optional[str] = None
    team_size: str
    primary_use_case: str


@router.post("/qualify")
def submit_qualification(
    body: OnboardingQualification,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user),
):
    if body.team_size not in VALID_TEAM_SIZES:
        raise HTTPException(status_code=400, detail=f"Invalid team_size. Must be one of: {', '.join(VALID_TEAM_SIZES)}")
    if body.primary_use_case not in VALID_USE_CASES:
        raise HTTPException(status_code=400, detail=f"Invalid primary_use_case. Must be one of: {', '.join(VALID_USE_CASES)}")

    company = db.query(Company).filter(Company.id == current_user.company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found.")

    if body.company_name:
        company.name = body.company_name
    company.team_size = body.team_size
    company.primary_use_case = body.primary_use_case
    company.onboarding_completed = True
    db.commit()
    return {"message": "Onboarding complete.", "company_id": company.id}


@router.get("/status")
class PlanSelection(BaseModel):
    plan_id: int


@router.post("/select-plan")
def select_plan(
    body: PlanSelection,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user),
):
    plan = db.query(SubscriptionPlan).filter(
        SubscriptionPlan.id == body.plan_id,
        SubscriptionPlan.is_active == True,
    ).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found.")

    subscription = db.query(CompanySubscription).filter(
        CompanySubscription.company_id == current_user.company_id
    ).first()
    if not subscription:
        raise HTTPException(status_code=404, detail="Subscription not found.")

    subscription.subscription_plan_id = plan.id
    subscription.user_limit = plan.default_user_limit
    db.commit()
    return {"message": "Plan selected.", "plan_id": plan.id, "plan_name": plan.name}


@router.get("/select-plan")
def get_plans_for_selection(db: Session = Depends(get_db)):
    """Return active plans for onboarding plan picker (public)."""
    plans = db.query(SubscriptionPlan).filter(SubscriptionPlan.is_active == True).order_by(SubscriptionPlan.price).all()
    return [
        {
            "id": p.id,
            "name": p.name,
            "price": p.price,
            "currency": p.currency,
            "description": p.description,
            "features": p.features,
            "default_user_limit": p.default_user_limit,
            "trial_days": p.trial_days,
            "billing_interval": p.billing_interval,
            "max_agents": p.max_agents,
            "max_monthly_conversations": p.max_monthly_conversations,
        }
        for p in plans
    ]


def get_onboarding_status(
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user),
):
    company = db.query(Company).filter(Company.id == current_user.company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found.")
    return {
        "onboarding_completed": company.onboarding_completed or False,
        "team_size": company.team_size,
        "primary_use_case": company.primary_use_case,
        "company_name": company.name,
        "email_verified": current_user.email_verified,
        "phone_verified": current_user.phone_verified,
    }
