from pydantic import BaseModel, ConfigDict
from typing import Optional, List
from datetime import datetime


class CalendarEventBase(BaseModel):
    title: str
    event_type: Optional[str] = "meeting"
    start_time: datetime
    end_time: datetime
    description: Optional[str] = None
    attendees: Optional[List[str]] = []


class CalendarEventCreate(CalendarEventBase):
    pass


class CalendarEventUpdate(BaseModel):
    title: Optional[str] = None
    event_type: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    description: Optional[str] = None
    attendees: Optional[List[str]] = None


class CalendarEventOut(CalendarEventBase):
    id: int
    user_id: int
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)
