from pydantic import BaseModel
from typing import Optional
import datetime

class Session(BaseModel):
    session_id: str
    status: str
    assignee_id: Optional[int] = None
    last_message_timestamp: datetime.datetime

    class Config:
        orm_mode = True
