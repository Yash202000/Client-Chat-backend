from pydantic import BaseModel
from typing import Optional

class WebhookBase(BaseModel):
    name: str
    url: str
    trigger_event: str
    is_active: Optional[bool] = True
    agent_id: int

class WebhookCreate(WebhookBase):
    pass

class WebhookUpdate(BaseModel):
    name: Optional[str] = None
    url: Optional[str] = None
    trigger_event: Optional[str] = None
    is_active: Optional[bool] = None

class Webhook(WebhookBase):
    id: int

    class Config:
        orm_mode = True
