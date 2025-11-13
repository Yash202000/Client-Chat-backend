from pydantic import BaseModel
from datetime import datetime
from typing import Optional

class NotificationBase(BaseModel):
    notification_type: str
    title: str
    message: str
    related_message_id: Optional[int] = None
    related_channel_id: Optional[int] = None

class NotificationCreate(NotificationBase):
    user_id: int
    actor_id: Optional[int] = None

class Notification(NotificationBase):
    id: int
    user_id: int
    actor_id: Optional[int] = None
    is_read: bool
    created_at: datetime
    read_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class NotificationCount(BaseModel):
    unread_count: int
