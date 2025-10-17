from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.core import security
from app.core.config import settings
from app.core.dependencies import get_db, get_current_active_user
from app.schemas import user as schemas_user, token as schemas_token, company as schemas_company
from app.services import user_service, company_service
from app.models import user as models_user

router = APIRouter()


@router.post("/signup", response_model=schemas_user.User)
def signup(user: schemas_user.UserCreate, db: Session = Depends(get_db)):
    db_user = user_service.get_user_by_email(db, email=user.email)
    if db_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    # For now, create a new company for each user signup.
    # In a real app, you might handle invitations or a default company.
    company = company_service.create_company(db, company=schemas_company.CompanyCreate(name=f"{user.email}'s Company"))
    
    return user_service.create_user(db=db, user=user, company_id=company.id)


@router.post("/login", response_model=schemas_token.Token)
def login_for_access_token(
    db: Session = Depends(get_db), form_data: OAuth2PasswordRequestForm = Depends()
):
    user = user_service.get_user_by_email(db, email=form_data.username)
    if not user or not security.verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Update user presence status to online
    user_service.update_user_presence(db, user.id, "online")

    access_token_expires = timedelta(minutes=60 * 24 * 7) # 7 days
    access_token = security.create_access_token(
        data={"sub": user.email}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer", "company_id": user.company_id}


@router.post("/logout")
def logout(
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    # Update user presence status to offline
    user_service.update_user_presence(db, current_user.id, "offline")
    return {"message": "Successfully logged out"}


@router.post("/presence")
def update_presence(
    presence_status: str,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Update current user's presence status.
    Valid values: online, offline, busy, away, do_not_disturb
    """
    valid_statuses = ["online", "offline", "busy", "away", "do_not_disturb"]
    if presence_status not in valid_statuses:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid presence status. Must be one of: {', '.join(valid_statuses)}"
        )

    updated_user = user_service.update_user_presence(db, current_user.id, presence_status)
    return {"presence_status": updated_user.presence_status, "last_seen": updated_user.last_seen}
