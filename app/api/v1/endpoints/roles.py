from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from typing import List

from app.core.dependencies import get_db, get_current_company, get_current_active_user
from app.models import user as models_user
from app.services import role_service
from app.schemas import role as schemas_role

router = APIRouter()

@router.post("/", response_model=schemas_role.Role)
def create_role(
    role: schemas_role.RoleCreate,
    db: Session = Depends(get_db),
    current_company_id: int = Depends(get_current_company),
    current_user: models_user.User = Depends(get_current_active_user)
):
    return role_service.create_role(db=db, role=role, company_id=current_company_id)

@router.get("/", response_model=List[schemas_role.Role])
def read_roles(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_company_id: int = Depends(get_current_company),
    current_user: models_user.User = Depends(get_current_active_user)
):
    roles = role_service.get_roles(db, company_id=current_company_id, skip=skip, limit=limit)
    return roles

@router.get("/{role_id}", response_model=schemas_role.Role)
def read_role(
    role_id: int,
    db: Session = Depends(get_db),
    current_company_id: int = Depends(get_current_company),
    current_user: models_user.User = Depends(get_current_active_user)
):
    db_role = role_service.get_role(db, role_id=role_id, company_id=current_company_id)
    if db_role is None:
        raise HTTPException(status_code=404, detail="Role not found")
    return db_role

@router.put("/{role_id}", response_model=schemas_role.Role)
def update_role(
    role_id: int,
    role: schemas_role.RoleUpdate,
    db: Session = Depends(get_db),
    current_company_id: int = Depends(get_current_company),
    current_user: models_user.User = Depends(get_current_active_user)
):
    return role_service.update_role(db=db, role_id=role_id, role=role, company_id=current_company_id)

@router.delete("/{role_id}", response_model=schemas_role.Role)
def delete_role(
    role_id: int,
    db: Session = Depends(get_db),
    current_company_id: int = Depends(get_current_company),
    current_user: models_user.User = Depends(get_current_active_user)
):
    db_role = role_service.delete_role(db, role_id=role_id, company_id=current_company_id)
    if db_role is None:
        raise HTTPException(status_code=404, detail="Role not found")
    return db_role
