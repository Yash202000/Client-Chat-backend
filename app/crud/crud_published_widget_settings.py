from sqlalchemy.orm import Session
from app.models.published_widget_settings import PublishedWidgetSettings
from app.schemas.published_widget_settings import PublishedWidgetSettingsCreate, PublishedWidgetSettingsUpdate
import json

def create_published_widget_settings(db: Session, settings: dict) -> PublishedWidgetSettings:
    db_settings = PublishedWidgetSettings(settings=json.dumps(settings))
    db.add(db_settings)
    db.commit()
    db.refresh(db_settings)
    return db_settings

def get_published_widget_settings(db: Session, publish_id: str) -> PublishedWidgetSettings:
    return db.query(PublishedWidgetSettings).filter(PublishedWidgetSettings.publish_id == publish_id).first()
