from pydantic import BaseModel
from typing import Optional, Dict, Any, Literal
import datetime

class AIImageBase(BaseModel):
    prompt: str
    generation_params: Optional[Dict[str, Any]] = None

class AIImageCreate(AIImageBase):
    provider: Literal["openai", "gemini"] = "openai"  # Default to OpenAI DALL-E
    size: Optional[str] = "1024x1024"  # For OpenAI: 1024x1024, 1792x1024, 1024x1792
    quality: Optional[str] = "standard"  # For OpenAI: standard, hd
    style: Optional[str] = "vivid"  # For OpenAI: vivid, natural

class AIImage(AIImageBase):
    id: int
    image_url: str
    created_at: datetime.datetime

    class Config:
        orm_mode = True
