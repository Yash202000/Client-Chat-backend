
from pydantic import BaseModel
from typing import Optional

class WidgetSettingsBase(BaseModel):
    primary_color: Optional[str] = None
    header_title: Optional[str] = None
    welcome_message: Optional[str] = None
    position: Optional[str] = None
    border_radius: Optional[int] = None
    font_family: Optional[str] = None
    agent_id: int

class WidgetSettingsCreate(WidgetSettingsBase):
    pass

class WidgetSettingsUpdate(WidgetSettingsBase):
    pass

class WidgetSettings(WidgetSettingsBase):
    id: int

    class Config:
        orm_mode = True
