from pydantic import BaseModel
from typing import Any

class MemoryBase(BaseModel):
    key: str
    value: Any

class MemoryCreate(MemoryBase):
    pass

class Memory(MemoryBase):
    id: int
    agent_id: int
    session_id: str

    class Config:
        from_attributes = True
