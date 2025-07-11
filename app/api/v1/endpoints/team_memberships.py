
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.schemas import team_membership as schemas_team_membership
from app.services import team_membership_service
from app.core.dependencies import get_db, get_current_company

router = APIRouter()

@router.post("/", response_model=schemas_team_membership.TeamMembership)
def create_team_membership(membership: schemas_team_membership.TeamMembershipCreate, db: Session = Depends(get_db), current_company_id: int = Depends(get_current_company)):
    return team_membership_service.create_team_membership(db=db, membership=membership, company_id=current_company_id)

@router.get("/by-team/{team_id}", response_model=List[schemas_team_membership.TeamMembership])
def read_team_memberships_by_team(team_id: int, db: Session = Depends(get_db), current_company_id: int = Depends(get_current_company)):
    memberships = team_membership_service.get_team_memberships_by_team(db, team_id=team_id, company_id=current_company_id)
    return memberships

@router.get("/by-user/{user_id}", response_model=List[schemas_team_membership.TeamMembership])
def read_team_memberships_by_user(user_id: int, db: Session = Depends(get_db), current_company_id: int = Depends(get_current_company)):
    memberships = team_membership_service.get_team_memberships_by_user(db, user_id=user_id, company_id=current_company_id)
    return memberships

@router.get("/{membership_id}", response_model=schemas_team_membership.TeamMembership)
def read_team_membership(membership_id: int, db: Session = Depends(get_db), current_company_id: int = Depends(get_current_company)):
    db_membership = team_membership_service.get_team_membership(db, membership_id=membership_id, company_id=current_company_id)
    if db_membership is None:
        raise HTTPException(status_code=404, detail="Team membership not found")
    return db_membership

@router.put("/{membership_id}", response_model=schemas_team_membership.TeamMembership)
def update_team_membership(membership_id: int, membership: schemas_team_membership.TeamMembershipUpdate, db: Session = Depends(get_db), current_company_id: int = Depends(get_current_company)):
    db_membership = team_membership_service.update_team_membership(db, membership_id=membership_id, membership=membership, company_id=current_company_id)
    if db_membership is None:
        raise HTTPException(status_code=404, detail="Team membership not found")
    return db_membership

@router.delete("/{membership_id}")
def delete_team_membership(membership_id: int, db: Session = Depends(get_db), current_company_id: int = Depends(get_current_company)):
    db_membership = team_membership_service.delete_team_membership(db, membership_id=membership_id, company_id=current_company_id)
    if db_membership is None:
        raise HTTPException(status_code=404, detail="Team membership not found")
    return {"message": "Team membership deleted successfully"}
