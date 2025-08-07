from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.core.dependencies import get_db, get_current_active_user
from app.models import user as models_user
from app.services import permission_service
from app.schemas import permission as schemas_permission

router = APIRouter()

@router.post("/", response_model=schemas_permission.Permission)
def create_permission(
    permission: schemas_permission.PermissionCreate, 
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    db_permission = permission_service.get_permission_by_name(db, name=permission.name)
    if db_permission:
        raise HTTPException(status_code=400, detail="Permission with this name already exists")
    return permission_service.create_permission(db=db, permission=permission)

@router.get("/", response_model=List[schemas_permission.Permission])
def read_permissions(
    skip: int = 0, 
    limit: int = 100, 
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    permissions = permission_service.get_permissions(db, skip=skip, limit=limit)
    return permissions

@router.get("/{permission_id}", response_model=schemas_permission.Permission)
def read_permission(
    permission_id: int, 
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    db_permission = permission_service.get_permission(db, permission_id=permission_id)
    if db_permission is None:
        raise HTTPException(status_code=404, detail="Permission not found")
    return db_permission
