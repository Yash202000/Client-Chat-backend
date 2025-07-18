
from sqlalchemy.orm import Session
from app.models.widget_settings import WidgetSettings
from app.schemas.widget_settings import WidgetSettingsCreate, WidgetSettingsUpdate
from app.core.config import settings

def get_widget_settings(db: Session, agent_id: int):
    settings_from_db = db.query(WidgetSettings).filter(WidgetSettings.agent_id == agent_id).first()
    if settings_from_db:
        if not settings_from_db.livekit_url:
            settings_from_db.livekit_url = settings.LIVEKIT_URL
        if not settings_from_db.frontend_url:
            settings_from_db.frontend_url = settings.FRONTEND_URL
        return settings_from_db
    return None

def create_widget_settings(db: Session, widget_settings: WidgetSettingsCreate):
    widget_settings_data = widget_settings.dict()
    widget_settings_data["livekit_url"] = settings.LIVEKIT_URL
    widget_settings_data["frontend_url"] = settings.FRONTEND_URL
    db_widget_settings = WidgetSettings(**widget_settings_data)
    db.add(db_widget_settings)
    db.commit()
    db.refresh(db_widget_settings)
    return db_widget_settings

def update_widget_settings(db: Session, agent_id: int, widget_settings: WidgetSettingsUpdate):
    db_widget_settings = get_widget_settings(db, agent_id)
    if db_widget_settings:
        update_data = widget_settings.dict(exclude_unset=True)
        for key, value in update_data.items():
            setattr(db_widget_settings, key, value)
        db.commit()
        db.refresh(db_widget_settings)
    return db_widget_settings
