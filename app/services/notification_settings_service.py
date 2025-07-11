
from sqlalchemy.orm import Session
from app.models import notification_settings as models_notification_settings
from app.schemas import notification_settings as schemas_notification_settings

def get_notification_settings(db: Session, company_id: int):
    return db.query(models_notification_settings.NotificationSettings).filter(models_notification_settings.NotificationSettings.company_id == company_id).first()

def create_notification_settings(db: Session, company_id: int, settings: schemas_notification_settings.NotificationSettingsCreate):
    db_settings = models_notification_settings.NotificationSettings(**settings.dict(), company_id=company_id)
    db.add(db_settings)
    db.commit()
    db.refresh(db_settings)
    return db_settings

def update_notification_settings(db: Session, company_id: int, settings: schemas_notification_settings.NotificationSettingsUpdate):
    db_settings = get_notification_settings(db, company_id)
    if db_settings:
        for key, value in settings.dict().items():
            setattr(db_settings, key, value)
        db.commit()
        db.refresh(db_settings)
    return db_settings
