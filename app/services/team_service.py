from sqlalchemy.orm import Session, joinedload
from app.models import team as models_team, user as models_user, team_membership as models_team_membership
from app.schemas import team as schemas_team

def get_team(db: Session, team_id: int, company_id: int):
    return db.query(models_team.Team).filter(models_team.Team.id == team_id, models_team.Team.company_id == company_id).first()

def get_teams(db: Session, company_id: int, skip: int = 0, limit: int = 100):
    return db.query(models_team.Team).options(joinedload(models_team.Team.members).joinedload(models_team_membership.TeamMembership.user)).filter(models_team.Team.company_id == company_id).offset(skip).limit(limit).all()

def create_team(db: Session, team: schemas_team.TeamCreate, company_id: int):
    db_team = models_team.Team(name=team.name, company_id=company_id)
    db.add(db_team)
    db.commit()
    db.refresh(db_team)
    return db_team

def update_team(db: Session, team_id: int, team: schemas_team.TeamUpdate, company_id: int):
    db_team = get_team(db, team_id, company_id)
    if db_team:
        update_data = team.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(db_team, key, value)
        db.commit()
        db.refresh(db_team)
    return db_team

def delete_team(db: Session, team_id: int, company_id: int):
    db_team = get_team(db, team_id, company_id)
    if db_team:
        db.delete(db_team)
        db.commit()
    return db_team