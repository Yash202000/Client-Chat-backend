
from pydantic import BaseModel
from typing import Optional, Dict, Any
import datetime

class AIImageBase(BaseModel):
    prompt: str
    generation_params: Optional[Dict[str, Any]] = None

class AIImageCreate(AIImageBase):
    pass

class AIImage(AIImageBase):
    id: int
    image_url: str
    created_at: datetime.datetime

    class Config:
        orm_mode = True
