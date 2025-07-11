
from sqlalchemy.orm import Session
from app.models import team_membership as models_team_membership
from app.schemas import team_membership as schemas_team_membership

def get_team_membership(db: Session, membership_id: int, company_id: int):
    return db.query(models_team_membership.TeamMembership).filter(models_team_membership.TeamMembership.id == membership_id, models_team_membership.TeamMembership.company_id == company_id).first()

def get_team_memberships_by_team(db: Session, team_id: int, company_id: int):
    return db.query(models_team_membership.TeamMembership).filter(models_team_membership.TeamMembership.team_id == team_id, models_team_membership.TeamMembership.company_id == company_id).all()

def get_team_memberships_by_user(db: Session, user_id: int, company_id: int):
    return db.query(models_team_membership.TeamMembership).filter(models_team_membership.TeamMembership.user_id == user_id, models_team_membership.TeamMembership.company_id == company_id).all()

def create_team_membership(db: Session, membership: schemas_team_membership.TeamMembershipCreate, company_id: int):
    db_membership = models_team_membership.TeamMembership(**membership.dict(), company_id=company_id)
    db.add(db_membership)
    db.commit()
    db.refresh(db_membership)
    return db_membership

def update_team_membership(db: Session, membership_id: int, membership: schemas_team_membership.TeamMembershipUpdate, company_id: int):
    db_membership = get_team_membership(db, membership_id, company_id)
    if db_membership:
        for key, value in membership.dict(exclude_unset=True).items():
            setattr(db_membership, key, value)
        db.commit()
        db.refresh(db_membership)
    return db_membership

def delete_team_membership(db: Session, membership_id: int, company_id: int):
    db_membership = get_team_membership(db, membership_id, company_id)
    if db_membership:
        db.delete(db_membership)
        db.commit()
    return db_membership
