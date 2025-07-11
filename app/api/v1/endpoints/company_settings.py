
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.schemas import company_settings as schemas_company_settings
from app.services import company_settings_service
from app.core.dependencies import get_db, get_current_company

router = APIRouter()

@router.get("/", response_model=schemas_company_settings.CompanySettings)
def read_company_settings(db: Session = Depends(get_db), current_company_id: int = Depends(get_current_company)):
    settings = company_settings_service.get_company_settings(db, company_id=current_company_id)
    if not settings:
        # If no settings exist, create them with default values
        default_settings = schemas_company_settings.CompanySettingsCreate(
            company_name="AgentConnect",
            support_email="support@agentconnect.com",
            timezone="UTC",
            language="en",
            business_hours=True
        )
        return company_settings_service.create_company_settings(db, current_company_id, default_settings)
    return settings

@router.put("/", response_model=schemas_company_settings.CompanySettings)
def update_company_settings(settings: schemas_company_settings.CompanySettingsUpdate, db: Session = Depends(get_db), current_company_id: int = Depends(get_current_company)):
    return company_settings_service.update_company_settings(db, company_id=current_company_id, settings=settings)
