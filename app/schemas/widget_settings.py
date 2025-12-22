
from pydantic import BaseModel
from typing import Optional, Dict, Any

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
    time_color: Optional[str] = None
    widget_size: Optional[str] = None
    widget_width: Optional[int] = None   # Custom width in px (overrides widget_size)
    widget_height: Optional[int] = None  # Custom height in px (overrides widget_size)
    show_header: Optional[bool] = None
    livekit_url: Optional[str] = None
    frontend_url: Optional[str] = None
    proactive_message_enabled: Optional[bool] = None
    proactive_message: Optional[str] = None
    proactive_message_delay: Optional[int] = None
    suggestions_enabled: Optional[bool] = None
    dark_mode: Optional[bool] = None
    typing_indicator_enabled: Optional[bool] = None
    communication_mode: Optional[str] = 'chat'
    meta: Optional[Dict[str, Any]] = None  # Flexible JSON field for additional customizations
    agent_id: int
    # Voice settings (from agent, not persisted in widget_settings)
    voice_id: Optional[str] = None
    stt_provider: Optional[str] = None
    tts_provider: Optional[str] = None

class WidgetSettingsCreate(WidgetSettingsBase):
    pass

class WidgetSettingsUpdate(WidgetSettingsBase):
    pass

class WidgetSettings(WidgetSettingsBase):
    id: int

    class Config:
        orm_mode = True
