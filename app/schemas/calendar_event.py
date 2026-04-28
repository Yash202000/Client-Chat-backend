from pydantic import BaseModel, ConfigDict
from typing import Optional, List
from datetime import datetime


class CalendarEventBase(BaseModel):
    title: str
    event_type: Optional[str] = "meeting"
    start_time: datetime
    end_time: datetime
    is_all_day: bool = False
    location: Optional[str] = None
    description: Optional[str] = None
    attendees: Optional[List[str]] = []
    livekit_room_name: Optional[str] = None
    recurrence_rule: Optional[str] = None       # daily|weekly|monthly
    recurrence_interval: Optional[int] = 1
    recurrence_end_date: Optional[datetime] = None


class CalendarEventCreate(CalendarEventBase):
    pass


class CalendarEventUpdate(BaseModel):
    title: Optional[str] = None
    event_type: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    is_all_day: Optional[bool] = None
    location: Optional[str] = None
    description: Optional[str] = None
    attendees: Optional[List[str]] = None
    livekit_room_name: Optional[str] = None
    recurrence_rule: Optional[str] = None
    recurrence_interval: Optional[int] = None
    recurrence_end_date: Optional[datetime] = None


class CalendarEventOut(CalendarEventBase):
    id: int
    user_id: int
    company_id: int
    parent_event_id: Optional[int] = None
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)
