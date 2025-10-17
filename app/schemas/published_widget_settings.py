from pydantic import BaseModel
from typing import Optional, Dict, Any

class PublishedWidgetSettingsBase(BaseModel):
    settings: Dict[str, Any]

class PublishedWidgetSettingsCreate(PublishedWidgetSettingsBase):
    pass

class PublishedWidgetSettingsUpdate(PublishedWidgetSettingsBase):
    pass

class PublishedWidgetSettings(PublishedWidgetSettingsBase):
    id: int
    publish_id: str

    class Config:
        orm_mode = True
