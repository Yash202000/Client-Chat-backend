from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from app.core.dependencies import get_db, get_current_active_user
from app.models import user as models_user
from app.models.company import Company

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
