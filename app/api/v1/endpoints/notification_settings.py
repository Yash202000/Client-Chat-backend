
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.schemas import notification_settings as schemas_notification_settings
from app.services import notification_settings_service
from app.core.dependencies import get_db, get_current_company, get_current_active_user
from app.models import user as models_user

router = APIRouter()

@router.get("/", response_model=schemas_notification_settings.NotificationSettings)
def read_notification_settings(db: Session = Depends(get_db), current_user: models_user.User = Depends(get_current_active_user)):
    settings = notification_settings_service.get_notification_settings(db, company_id=current_user.company_id)
    if not settings:
        default_settings = schemas_notification_settings.NotificationSettingsCreate(
            email_notifications_enabled=True,
            slack_notifications_enabled=False,
            auto_assignment_enabled=True
        )
        return notification_settings_service.create_notification_settings(db, current_user.company_id, default_settings)
    return settings

@router.put("/", response_model=schemas_notification_settings.NotificationSettings)
def update_notification_settings(settings: schemas_notification_settings.NotificationSettingsUpdate, db: Session = Depends(get_db), current_user: models_user.User = Depends(get_current_active_user)):
    return notification_settings_service.update_notification_settings(db, current_user.company_id, settings)
