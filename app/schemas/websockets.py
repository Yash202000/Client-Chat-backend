from pydantic import BaseModel
from typing import Any, Literal

class WebSocketMessage(BaseModel):
    type: str
    payload: Any
