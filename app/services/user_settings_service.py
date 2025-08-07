
from sqlalchemy.orm import Session
from app.models import user_settings as models_user_settings
from app.schemas import user_settings as schemas_user_settings

def get_user_settings(db: Session, user_id: int, company_id: int):
    return db.query(models_user_settings.UserSettings).filter(models_user_settings.UserSettings.user_id == user_id, models_user_settings.UserSettings.company_id == company_id).first()

def create_user_settings(db: Session, user_id: int, company_id: int, settings: schemas_user_settings.UserSettingsCreate):
    db_settings = models_user_settings.UserSettings(**settings.model_dump(), user_id=user_id, company_id=company_id)
    db.add(db_settings)
    db.commit()
    db.refresh(db_settings)
    return db_settings

def update_user_settings(db: Session, user_id: int, company_id: int, settings: schemas_user_settings.UserSettingsUpdate):
    db_settings = get_user_settings(db, user_id, company_id)
    if db_settings:
        for key, value in settings.model_dump().items():
            setattr(db_settings, key, value)
        db.commit()
        db.refresh(db_settings)
    return db_settings
