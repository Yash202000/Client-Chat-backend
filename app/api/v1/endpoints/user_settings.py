
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.schemas import user_settings as schemas_user_settings
from app.services import user_settings_service
from app.core.dependencies import get_db, get_current_company

router = APIRouter()

@router.get("/{user_id}", response_model=schemas_user_settings.UserSettings)
def read_user_settings(user_id: int, db: Session = Depends(get_db), current_company_id: int = Depends(get_current_company)):
    settings = user_settings_service.get_user_settings(db, user_id=user_id, company_id=current_company_id)
    if not settings:
        # If no settings exist, create them with default values
        default_settings = schemas_user_settings.UserSettingsCreate()
        return user_settings_service.create_user_settings(db, user_id, current_company_id, default_settings)
    return settings

@router.put("/{user_id}", response_model=schemas_user_settings.UserSettings)
def update_user_settings(user_id: int, settings: schemas_user_settings.UserSettingsUpdate, db: Session = Depends(get_db), current_company_id: int = Depends(get_current_company)):
    db_settings = user_settings_service.update_user_settings(db, user_id=user_id, company_id=current_company_id, settings=settings)
    if db_settings is None:
        raise HTTPException(status_code=404, detail="Settings not found")
    return db_settings
