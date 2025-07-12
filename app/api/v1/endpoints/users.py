
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.schemas import user as schemas_user
from app.services import user_service
from app.core.dependencies import get_db, get_current_company

router = APIRouter()

@router.post("/", response_model=schemas_user.User)
def create_user(user: schemas_user.UserCreate, db: Session = Depends(get_db), current_company_id: int = Depends(get_current_company)):
    db_user = user_service.get_user_by_email(db, email=user.email, company_id=current_company_id)
    if db_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    return user_service.create_user(db=db, user=user, company_id=current_company_id)

@router.get("/", response_model=List[schemas_user.User])
def read_users(skip: int = 0, limit: int = 100, db: Session = Depends(get_db), current_company_id: int = Depends(get_current_company)):
    users = user_service.get_users(db, company_id=current_company_id, skip=skip, limit=limit)
    return users

@router.get("/{user_id}", response_model=schemas_user.User)
def read_user(user_id: int, db: Session = Depends(get_db), current_company_id: int = Depends(get_current_company)):
    db_user = user_service.get_user(db, user_id=user_id, company_id=current_company_id)
    if db_user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return db_user
