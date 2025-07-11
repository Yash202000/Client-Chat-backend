
from pydantic import BaseModel

class NotificationSettingsBase(BaseModel):
    email_notifications_enabled: bool
    slack_notifications_enabled: bool
    auto_assignment_enabled: bool

class NotificationSettingsCreate(NotificationSettingsBase):
    pass

class NotificationSettingsUpdate(NotificationSettingsBase):
    pass

class NotificationSettings(NotificationSettingsBase):
    id: int
    company_id: int

    class Config:
        orm_mode = True
