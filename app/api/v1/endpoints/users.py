
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app.schemas import user as schemas_user
from app.services import user_service
from app.core.dependencies import get_db, get_current_active_user, get_current_company
from app.models import user as models_user

router = APIRouter()

def get_current_admin_user(current_user: models_user.User = Depends(get_current_active_user)):
    if not current_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to perform this action")
    return current_user

@router.get("/me", response_model=schemas_user.User)
def read_users_me(current_user: models_user.User = Depends(get_current_active_user)):
    return current_user

@router.post("/", response_model=schemas_user.User, status_code=status.HTTP_201_CREATED)
def create_user(
    user: schemas_user.UserCreate,
    db: Session = Depends(get_db),
    current_company_id: int = Depends(get_current_company),
    current_user: models_user.User = Depends(get_current_active_user) # Ensure user is authenticated
):
    db_user = user_service.get_user_by_email(db, email=user.email)
    if db_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    # Only an admin can create new users if there's already an admin
    if not current_user.is_admin and db.query(models_user.User).filter(models_user.User.company_id == current_company_id, models_user.User.is_admin == True).first():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only administrators can create new users.")

    return user_service.create_user(db=db, user=user, company_id=current_company_id)

@router.get("/", response_model=List[schemas_user.User])
def read_users(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_company_id: int = Depends(get_current_company),
    current_user: models_user.User = Depends(get_current_admin_user) # Only admins can list all users
):
    users = user_service.get_users(db, company_id=current_company_id, skip=skip, limit=limit)
    return users

@router.get("/{user_id}", response_model=schemas_user.User)
def read_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_company_id: int = Depends(get_current_company),
    current_user: models_user.User = Depends(get_current_admin_user) # Only admins can read specific user details
):
    db_user = user_service.get_user(db, user_id=user_id)
    if not db_user or db_user.company_id != current_company_id:
        raise HTTPException(status_code=404, detail="User not found")
    return db_user

@router.put("/{user_id}/activate", response_model=schemas_user.User)
def activate_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_company_id: int = Depends(get_current_company),
    current_user: models_user.User = Depends(get_current_admin_user)
):
    db_user = user_service.get_user(db, user_id=user_id)
    if not db_user or db_user.company_id != current_company_id:
        raise HTTPException(status_code=404, detail="User not found")
    
    updated_user = user_service.update_user(db, db_obj=db_user, obj_in=schemas_user.UserUpdate(is_active=True))
    return updated_user

@router.put("/{user_id}/deactivate", response_model=schemas_user.User)
def deactivate_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_company_id: int = Depends(get_current_company),
    current_user: models_user.User = Depends(get_current_admin_user)
):
    db_user = user_service.get_user(db, user_id=user_id)
    if not db_user or db_user.company_id != current_company_id:
        raise HTTPException(status_code=404, detail="User not found")
    
    updated_user = user_service.update_user(db, db_obj=db_user, obj_in=schemas_user.UserUpdate(is_active=False))
    return updated_user

@router.put("/{user_id}/set-admin", response_model=schemas_user.User)
def set_user_admin_status(
    user_id: int,
    is_admin: bool,
    db: Session = Depends(get_db),
    current_company_id: int = Depends(get_current_company),
    current_user: models_user.User = Depends(get_current_admin_user)
):
    db_user = user_service.get_user(db, user_id=user_id)
    if not db_user or db_user.company_id != current_company_id:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Prevent an admin from deactivating their own admin status
    if current_user.id == user_id and not is_admin:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot revoke your own admin status.")

    updated_user = user_service.update_user(db, db_obj=db_user, obj_in=schemas_user.UserUpdate(is_admin=is_admin))
    return updated_user
