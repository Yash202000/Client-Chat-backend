from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from datetime import datetime


class CampaignMessageBase(BaseModel):
    campaign_id: int
    sequence_order: int
    name: Optional[str] = None
    message_type: str  # email, sms, whatsapp, voice, ai_conversation
    subject: Optional[str] = None
    body: Optional[str] = None
    html_body: Optional[str] = None
    voice_script: Optional[str] = None
    tts_voice_id: Optional[str] = None
    voice_agent_id: Optional[int] = None
    twilio_phone_number: Optional[str] = None
    call_flow_config: Optional[Dict[str, Any]] = None
    whatsapp_template_name: Optional[str] = None
    whatsapp_template_params: Optional[Dict[str, Any]] = None
    delay_amount: Optional[int] = 0
    delay_unit: Optional[str] = "days"
    send_time_window_start: Optional[str] = None
    send_time_window_end: Optional[str] = None
    send_on_weekdays_only: Optional[bool] = False
    is_ab_test: Optional[bool] = False
    ab_variant: Optional[str] = None
    ab_split_percentage: Optional[int] = None
    personalization_tokens: Optional[List[str]] = None
    cta_text: Optional[str] = None
    cta_url: Optional[str] = None
    track_clicks: Optional[bool] = True
    send_conditions: Optional[Dict[str, Any]] = None
    is_active: Optional[bool] = True


class CampaignMessageCreate(CampaignMessageBase):
    pass


class CampaignMessageUpdate(BaseModel):
    sequence_order: Optional[int] = None
    name: Optional[str] = None
    message_type: Optional[str] = None
    subject: Optional[str] = None
    body: Optional[str] = None
    html_body: Optional[str] = None
    voice_script: Optional[str] = None
    tts_voice_id: Optional[str] = None
    voice_agent_id: Optional[int] = None
    twilio_phone_number: Optional[str] = None
    call_flow_config: Optional[Dict[str, Any]] = None
    whatsapp_template_name: Optional[str] = None
    whatsapp_template_params: Optional[Dict[str, Any]] = None
    delay_amount: Optional[int] = None
    delay_unit: Optional[str] = None
    send_time_window_start: Optional[str] = None
    send_time_window_end: Optional[str] = None
    send_on_weekdays_only: Optional[bool] = None
    is_ab_test: Optional[bool] = None
    ab_variant: Optional[str] = None
    ab_split_percentage: Optional[int] = None
    personalization_tokens: Optional[List[str]] = None
    cta_text: Optional[str] = None
    cta_url: Optional[str] = None
    track_clicks: Optional[bool] = None
    send_conditions: Optional[Dict[str, Any]] = None
    is_active: Optional[bool] = None


class CampaignMessage(CampaignMessageBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
