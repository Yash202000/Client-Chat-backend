
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional

from app.schemas import user as schemas_user
from app.services import user_service
from app.core.dependencies import get_db, get_current_active_user, require_permission, require_user_limit_not_exceeded
from app.core.audit import log_action
from app.models import user as models_user

router = APIRouter()

@router.get("/me", response_model=schemas_user.UserWithSuperAdmin)
def read_users_me(current_user: models_user.User = Depends(get_current_active_user)):
    return current_user

@router.post("/", response_model=schemas_user.User, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission("user:create")), Depends(require_user_limit_not_exceeded)])
def create_user(
    user: schemas_user.UserCreate,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    db_user = user_service.get_user_by_email(db, email=user.email)
    if db_user:
        raise HTTPException(status_code=400, detail="Email already registered")

    new_user = user_service.create_user(db=db, user=user, company_id=current_user.company_id, role_id=user.role_id)
    log_action(db, company_id=current_user.company_id, user_id=current_user.id,
               action="user.created", entity_type="user",
               entity_id=new_user.id, entity_name=new_user.email)
    db.commit()
    return new_user

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

    old_role_id = db_user.role_id
    old_active = db_user.is_active
    updated_user = user_service.update_user(db, db_obj=db_user, obj_in=user_update)

    if user_update.role_id is not None and user_update.role_id != old_role_id:
        log_action(db, company_id=current_user.company_id, user_id=current_user.id,
                   action="user.role_changed", entity_type="user",
                   entity_id=updated_user.id, entity_name=updated_user.email,
                   changes={"old_role_id": old_role_id, "new_role_id": user_update.role_id})
    if user_update.is_active is not None and user_update.is_active != old_active:
        action = "user.activated" if user_update.is_active else "user.deactivated"
        log_action(db, company_id=current_user.company_id, user_id=current_user.id,
                   action=action, entity_type="user",
                   entity_id=updated_user.id, entity_name=updated_user.email)
    db.commit()
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

    deleted_email = db_user.email
    result = user_service.delete_user(db, user_id=user_id)
    log_action(db, company_id=current_user.company_id, user_id=current_user.id,
               action="user.deleted", entity_type="user",
               entity_id=user_id, entity_name=deleted_email)
    db.commit()
    return {"ok": result["success"], "action": result["action"]}
