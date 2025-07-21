
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.schemas import company_settings as schemas_company_settings
from app.services import company_settings_service
from app.core.dependencies import get_db, get_current_company, get_current_active_user
from app.models import user as models_user

router = APIRouter()

@router.get("/", response_model=schemas_company_settings.CompanySettings)
def read_company_settings(db: Session = Depends(get_db), current_company_id: int = Depends(get_current_company), current_user: models_user.User = Depends(get_current_active_user)):
    settings = company_settings_service.get_company_settings(db, company_id=current_company_id)
    print(settings)
    if not settings:
        username = current_user.email.split('@')[0]
        # If no settings exist, create them with default values
        default_settings = schemas_company_settings.CompanySettingsCreate(
            company_name=f"{username}'s company",
            support_email=current_user.email,
            timezone="UTC",
            language="en",
            business_hours=True
        )
        return company_settings_service.create_company_settings(db, current_company_id, default_settings)
    return settings

@router.put("/", response_model=schemas_company_settings.CompanySettings)
def update_company_settings(settings: schemas_company_settings.CompanySettingsUpdate, db: Session = Depends(get_db), current_company_id: int = Depends(get_current_company), current_user: models_user.User = Depends(get_current_active_user)):
    return company_settings_service.update_company_settings(db, company_id=current_company_id, settings=settings)
