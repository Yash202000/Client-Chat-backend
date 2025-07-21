
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.schemas import user_settings as schemas_user_settings
from app.services import user_settings_service
from app.core.dependencies import get_db, get_current_company, get_current_active_user
from app.models import user as models_user

router = APIRouter()

@router.get("/", response_model=schemas_user_settings.UserSettings)
def read_user_settings(db: Session = Depends(get_db), current_user: models_user.User = Depends(get_current_active_user)):
    settings = user_settings_service.get_user_settings(db, user_id=current_user.id, company_id=current_user.company_id)
    print(settings.company,settings.owner)
    if not settings:
        # If no settings exist, create them with default values
        default_settings = schemas_user_settings.UserSettingsCreate()
        return user_settings_service.create_user_settings(db, current_user.id, current_user.company_id, default_settings)
    return settings

@router.put("/", response_model=schemas_user_settings.UserSettings)
def update_user_settings(settings: schemas_user_settings.UserSettingsUpdate, db: Session = Depends(get_db), current_user: models_user.User = Depends(get_current_active_user)):
    db_settings = user_settings_service.update_user_settings(db, user_id=current_user.id, company_id=current_user.company_id, settings=settings)
    if db_settings is None:
        raise HTTPException(status_code=404, detail="Settings not found")
    return db_settings
