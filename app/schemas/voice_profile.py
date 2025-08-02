
from pydantic import BaseModel
from typing import Optional

class VoiceProfileBase(BaseModel):
    name: str

class VoiceProfileCreate(VoiceProfileBase):
    pass

class VoiceProfileUpdate(VoiceProfileBase):
    pass

class VoiceProfile(VoiceProfileBase):
    id: int
    provider_voice_id: str
    company_id: int
    user_id: Optional[int] = None

    class Config:
        from_attributes = True
