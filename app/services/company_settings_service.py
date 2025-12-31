
from sqlalchemy.orm import Session
from app.models import company_settings as models_company_settings
from app.schemas import company_settings as schemas_company_settings

def get_company_settings(db: Session, company_id: int):
    return db.query(models_company_settings.CompanySettings).filter(models_company_settings.CompanySettings.company_id == company_id).first()

def create_company_settings(db: Session, company_id: int, settings: schemas_company_settings.CompanySettingsCreate):
    db_settings = models_company_settings.CompanySettings(**settings.model_dump(), company_id=company_id)
    db.add(db_settings)
    db.commit()
    db.refresh(db_settings)
    return db_settings

def update_company_settings(db: Session, company_id: int, settings: schemas_company_settings.CompanySettingsUpdate):
    db_settings = get_company_settings(db, company_id)
    if db_settings:
        # Use exclude_unset=True to only update fields that were explicitly set
        for key, value in settings.model_dump(exclude_unset=True).items():
            setattr(db_settings, key, value)
        db.commit()
        db.refresh(db_settings)
    return db_settings
