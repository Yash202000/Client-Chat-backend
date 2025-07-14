from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from typing import List, Optional

from app.core.dependencies import get_db
from app.services import team_service, team_membership_service, user_service
from app.schemas import team as schemas_team, team_membership as schemas_team_membership, user as schemas_user

router = APIRouter()

@router.post("/", response_model=schemas_team.Team)
def create_team(
    team: schemas_team.TeamCreate,
    db: Session = Depends(get_db),
    x_company_id: Optional[int] = Header(None),
):
    if x_company_id is None:
        raise HTTPException(status_code=400, detail="X-Company-ID header is required")
    return team_service.create_team(db=db, team=team, company_id=x_company_id)

@router.get("/", response_model=List[schemas_team.Team])
def read_teams(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    x_company_id: Optional[int] = Header(None),
):
    if x_company_id is None:
        raise HTTPException(status_code=400, detail="X-Company-ID header is required")
    teams = team_service.get_teams(db, company_id=x_company_id, skip=skip, limit=limit)
    return teams

@router.get("/{team_id}", response_model=schemas_team.Team)
def read_team(
    team_id: int,
    db: Session = Depends(get_db),
    x_company_id: Optional[int] = Header(None),
):
    if x_company_id is None:
        raise HTTPException(status_code=400, detail="X-Company-ID header is required")
    db_team = team_service.get_team(db, team_id=team_id, company_id=x_company_id)
    if db_team is None:
        raise HTTPException(status_code=404, detail="Team not found")
    return db_team

@router.put("/{team_id}", response_model=schemas_team.Team)
def update_team(
    team_id: int,
    team: schemas_team.TeamUpdate,
    db: Session = Depends(get_db),
    x_company_id: Optional[int] = Header(None),
):
    if x_company_id is None:
        raise HTTPException(status_code=400, detail="X-Company-ID header is required")
    db_team = team_service.update_team(db=db, team_id=team_id, team=team, company_id=x_company_id)
    if db_team is None:
        raise HTTPException(status_code=404, detail="Team not found")
    return db_team

@router.delete("/{team_id}", response_model=schemas_team.Team)
def delete_team(
    team_id: int,
    db: Session = Depends(get_db),
    x_company_id: Optional[int] = Header(None),
):
    if x_company_id is None:
        raise HTTPException(status_code=400, detail="X-Company-ID header is required")
    db_team = team_service.delete_team(db, team_id=team_id, company_id=x_company_id)
    if db_team is None:
        raise HTTPException(status_code=404, detail="Team not found")
    return db_team

@router.post("/{team_id}/members", response_model=schemas_team_membership.TeamMembership)
def add_team_member(
    team_id: int,
    member: schemas_team_membership.TeamMembershipCreate,
    db: Session = Depends(get_db),
    x_company_id: Optional[int] = Header(None),
):
    if x_company_id is None:
        raise HTTPException(status_code=400, detail="X-Company-ID header is required")
    return team_membership_service.add_member_to_team(
        db=db, team_id=team_id, user_id=member.user_id, role=member.role, company_id=x_company_id
    )

@router.delete("/{team_id}/members/{user_id}", response_model=schemas_team_membership.TeamMembership)
def remove_team_member(
    team_id: int,
    user_id: int,
    db: Session = Depends(get_db),
    x_company_id: Optional[int] = Header(None),
):
    if x_company_id is None:
        raise HTTPException(status_code=400, detail="X-Company-ID header is required")
    return team_membership_service.remove_member_from_team(
        db=db, team_id=team_id, user_id=user_id, company_id=x_company_id
    )

@router.get("/{team_id}/members", response_model=List[schemas_user.User])
def get_team_members(
    team_id: int,
    db: Session = Depends(get_db),
    x_company_id: Optional[int] = Header(None),
):
    if x_company_id is None:
        raise HTTPException(status_code=400, detail="X-Company-ID header is required")
    return team_membership_service.get_team_members(db=db, team_id=team_id, company_id=x_company_id)

@router.put("/{team_id}/members/{user_id}", response_model=schemas_team_membership.TeamMembership)
def update_team_member_role(
    team_id: int,
    user_id: int,
    member: schemas_team_membership.TeamMembershipUpdate,
    db: Session = Depends(get_db),
    x_company_id: Optional[int] = Header(None),
):
    if x_company_id is None:
        raise HTTPException(status_code=400, detail="X-Company-ID header is required")
    return team_membership_service.update_member_role(
        db=db, team_id=team_id, user_id=user_id, role=member.role, company_id=x_company_id
    )
