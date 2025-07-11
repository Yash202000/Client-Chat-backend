
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.schemas import team as schemas_team
from app.services import team_service
from app.core.dependencies import get_db, get_current_company

router = APIRouter()

@router.post("/", response_model=schemas_team.Team)
def create_team(team: schemas_team.TeamCreate, db: Session = Depends(get_db), current_company_id: int = Depends(get_current_company)):
    db_team = team_service.get_team_by_name(db, name=team.name, company_id=current_company_id)
    if db_team:
        raise HTTPException(status_code=400, detail="Team with this name already exists")
    return team_service.create_team(db=db, team=team, company_id=current_company_id)

@router.get("/", response_model=List[schemas_team.Team])
def read_teams(skip: int = 0, limit: int = 100, db: Session = Depends(get_db), current_company_id: int = Depends(get_current_company)):
    teams = team_service.get_teams(db, company_id=current_company_id, skip=skip, limit=limit)
    return teams

@router.get("/{team_id}", response_model=schemas_team.Team)
def read_team(team_id: int, db: Session = Depends(get_db), current_company_id: int = Depends(get_current_company)):
    db_team = team_service.get_team(db, team_id=team_id, company_id=current_company_id)
    if db_team is None:
        raise HTTPException(status_code=404, detail="Team not found")
    return db_team

@router.put("/{team_id}", response_model=schemas_team.Team)
def update_team(team_id: int, team: schemas_team.TeamUpdate, db: Session = Depends(get_db), current_company_id: int = Depends(get_current_company)):
    db_team = team_service.update_team(db, team_id=team_id, team=team, company_id=current_company_id)
    if db_team is None:
        raise HTTPException(status_code=404, detail="Team not found")
    return db_team

@router.delete("/{team_id}")
def delete_team(team_id: int, db: Session = Depends(get_db), current_company_id: int = Depends(get_current_company)):
    db_team = team_service.delete_team(db, team_id=team_id, company_id=current_company_id)
    if db_team is None:
        raise HTTPException(status_code=404, detail="Team not found")
    return {"message": "Team deleted successfully"}
