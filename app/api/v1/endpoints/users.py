
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional

from app.schemas import user as schemas_user
from app.services import user_service
from app.core.dependencies import get_db, get_current_active_user, require_permission
from app.models import user as models_user

router = APIRouter()

@router.get("/me", response_model=schemas_user.UserWithSuperAdmin)
def read_users_me(current_user: models_user.User = Depends(get_current_active_user)):
    return current_user

@router.post("/", response_model=schemas_user.User, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission("user:create"))])
def create_user(
    user: schemas_user.UserCreate,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    db_user = user_service.get_user_by_email(db, email=user.email)
    if db_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    return user_service.create_user(db=db, user=user, company_id=current_user.company_id, role_id=user.role_id)

@router.get("/", response_model=List[schemas_user.User], dependencies=[Depends(require_permission("user:read"))])
def read_users(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    users = user_service.get_users(db, company_id=current_user.company_id, skip=skip, limit=limit)
    return users

@router.get("/{user_id}", response_model=schemas_user.User, dependencies=[Depends(require_permission("user:read"))])
def read_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    db_user = user_service.get_user(db, user_id=user_id)
    if not db_user or db_user.company_id != current_user.company_id:
        raise HTTPException(status_code=404, detail="User not found")
    return db_user

@router.put("/{user_id}", response_model=schemas_user.User, dependencies=[Depends(require_permission("user:update"))])
def update_user(
    user_id: int,
    user_update: schemas_user.UserUpdate,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    db_user = user_service.get_user(db, user_id=user_id)
    if not db_user or db_user.company_id != current_user.company_id:
        raise HTTPException(status_code=404, detail="User not found")

    # Prevent a user from changing their own role
    if user_update.role_id is not None and current_user.id == user_id:
        if db_user.role_id != user_update.role_id:
            raise HTTPException(status_code=400, detail="Cannot change your own role.")

    updated_user = user_service.update_user(db, db_obj=db_user, obj_in=user_update)
    return updated_user

@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_permission("user:delete"))])
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    db_user = user_service.get_user(db, user_id=user_id)
    if not db_user or db_user.company_id != current_user.company_id:
        raise HTTPException(status_code=404, detail="User not found")
    
    if current_user.id == user_id:
        raise HTTPException(status_code=400, detail="Cannot delete your own account.")

    user_service.delete_user(db, user_id=user_id)
    return {"ok": True}
