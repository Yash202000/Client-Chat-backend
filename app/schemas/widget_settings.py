
from pydantic import BaseModel
from typing import Optional

class WidgetSettingsBase(BaseModel):
    primary_color: Optional[str] = None
    header_title: Optional[str] = None
    welcome_message: Optional[str] = None
    position: Optional[str] = None
    border_radius: Optional[int] = None
    font_family: Optional[str] = None
    agent_avatar_url: Optional[str] = None
    input_placeholder: Optional[str] = None
    user_message_color: Optional[str] = None
    user_message_text_color: Optional[str] = None
    bot_message_color: Optional[str] = None
    bot_message_text_color: Optional[str] = None
    widget_size: Optional[str] = None
    show_header: Optional[bool] = None
    livekit_url: Optional[str] = None
    frontend_url: Optional[str] = None
    proactive_message_enabled: Optional[bool] = None
    proactive_message: Optional[str] = None
    proactive_message_delay: Optional[int] = None
    suggestions_enabled: Optional[bool] = None
    agent_id: int

class WidgetSettingsCreate(WidgetSettingsBase):
    pass

class WidgetSettingsUpdate(WidgetSettingsBase):
    pass

class WidgetSettings(WidgetSettingsBase):
    id: int

    class Config:
        orm_mode = True
