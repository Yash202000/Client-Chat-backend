from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.schemas.user import User, UserUpdate
from app.services.user_service import get_user_by_email, update_user
from app.core.auth import get_current_user

router = APIRouter()


@router.get("/me", response_model=User)
def read_users_me(current_user: User = Depends(get_current_user)):
    return current_user


@router.put("/me", response_model=User)
def update_users_me(
    *,
    db: Session = Depends(get_db),
    user_in: UserUpdate,
    current_user: User = Depends(get_current_user)
):
    user = update_user(db, db_obj=current_user, obj_in=user_in)
    return user
