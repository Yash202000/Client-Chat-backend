
from sqlalchemy.orm import Session
from app.models.widget_settings import WidgetSettings
from app.schemas.widget_settings import WidgetSettingsCreate, WidgetSettingsUpdate

def get_widget_settings(db: Session, agent_id: int):
    return db.query(WidgetSettings).filter(WidgetSettings.agent_id == agent_id).first()

def create_widget_settings(db: Session, widget_settings: WidgetSettingsCreate):
    db_widget_settings = WidgetSettings(**widget_settings.dict())
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
