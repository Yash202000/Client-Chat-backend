from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app.core.dependencies import get_db
from app.schemas import subscription_plan as schemas_subscription_plan
from app.services import subscription_service
from app.core.auth import get_current_user
from app.models.user import User

router = APIRouter()

@router.post("/plans/", response_model=schemas_subscription_plan.SubscriptionPlan, status_code=status.HTTP_201_CREATED)
def create_subscription_plan(
    plan: schemas_subscription_plan.SubscriptionPlanCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user) # Only authenticated users can create plans
):
    # Optional: Add role-based access control here (e.g., only admins can create plans)
    if not current_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to create subscription plans")
    
    db_plan = subscription_service.get_subscription_plan_by_name(db, name=plan.name)
    if db_plan:
        raise HTTPException(status_code=400, detail="Subscription plan with this name already exists")
    return subscription_service.create_subscription_plan(db=db, plan=plan)

@router.get("/plans/", response_model=List[schemas_subscription_plan.SubscriptionPlan])
def read_subscription_plans(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    plans = subscription_service.get_subscription_plans(db, skip=skip, limit=limit)
    return plans

@router.get("/plans/{plan_id}", response_model=schemas_subscription_plan.SubscriptionPlan)
def read_subscription_plan(
    plan_id: int,
    db: Session = Depends(get_db)
):
    db_plan = subscription_service.get_subscription_plan(db, plan_id=plan_id)
    if db_plan is None:
        raise HTTPException(status_code=404, detail="Subscription plan not found")
    return db_plan

@router.put("/plans/{plan_id}", response_model=schemas_subscription_plan.SubscriptionPlan)
def update_subscription_plan(
    plan_id: int,
    plan: schemas_subscription_plan.SubscriptionPlanUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if not current_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to update subscription plans")

    db_plan = subscription_service.update_subscription_plan(db, plan_id=plan_id, plan=plan)
    if db_plan is None:
        raise HTTPException(status_code=404, detail="Subscription plan not found")
    return db_plan

@router.delete("/plans/{plan_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_subscription_plan(
    plan_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if not current_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to delete subscription plans")

    db_plan = subscription_service.delete_subscription_plan(db, plan_id=plan_id)
    if db_plan is None:
        raise HTTPException(status_code=404, detail="Subscription plan not found")
    return None
