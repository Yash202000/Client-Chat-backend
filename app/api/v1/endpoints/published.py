from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.dependencies import get_db
from app.crud import crud_published_widget_settings
from app.schemas.published_widget_settings import PublishedWidgetSettings
import json

router = APIRouter()

@router.get("/{publish_id}", response_model=PublishedWidgetSettings)
def read_published_widget_settings(publish_id: str, db: Session = Depends(get_db)):
    db_settings = crud_published_widget_settings.get_published_widget_settings(db, publish_id=publish_id)

    if db_settings is None:
        raise HTTPException(status_code=404, detail="Published settings not found")

    # Check if the widget is active (not unpublished)
    if not db_settings.is_active:
        raise HTTPException(status_code=404, detail="This widget has been unpublished")

    # The settings are stored as a JSON string, so we need to parse it.
    db_settings.settings = json.loads(db_settings.settings)
    return db_settings
