from pydantic import BaseModel
from typing import Optional

class ProactiveMessageCreate(BaseModel):
    contact_id: Optional[int] = None
    session_id: Optional[str] = None
    text: str
