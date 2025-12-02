from sqlalchemy.orm import Session
from app.models import subscription_plan as models_subscription_plan
from app.schemas import subscription_plan as schemas_subscription_plan

def get_subscription_plan(db: Session, plan_id: int):
    return db.query(models_subscription_plan.SubscriptionPlan).filter(models_subscription_plan.SubscriptionPlan.id == plan_id).first()

def get_subscription_plan_by_name(db: Session, name: str):
    return db.query(models_subscription_plan.SubscriptionPlan).filter(models_subscription_plan.SubscriptionPlan.name == name).first()

def get_subscription_plans(db: Session, skip: int = 0, limit: int = 100):
    return db.query(models_subscription_plan.SubscriptionPlan).offset(skip).limit(limit).all()

def create_subscription_plan(db: Session, plan: schemas_subscription_plan.SubscriptionPlanCreate):
    db_plan = models_subscription_plan.SubscriptionPlan(**plan.dict())
    db.add(db_plan)
    db.commit()
    db.refresh(db_plan)
    return db_plan

def update_subscription_plan(db: Session, plan_id: int, plan: schemas_subscription_plan.SubscriptionPlanUpdate):
    db_plan = db.query(models_subscription_plan.SubscriptionPlan).filter(models_subscription_plan.SubscriptionPlan.id == plan_id).first()
    if db_plan:
        for key, value in plan.model_dump(exclude_unset=True).items():
            setattr(db_plan, key, value)
        db.commit()
        db.refresh(db_plan)
    return db_plan

def delete_subscription_plan(db: Session, plan_id: int):
    db_plan = db.query(models_subscription_plan.SubscriptionPlan).filter(models_subscription_plan.SubscriptionPlan.id == plan_id).first()
    if db_plan:
        db.delete(db_plan)
        db.commit()
    return db_plan
