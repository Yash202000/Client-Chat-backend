from pydantic import BaseModel
from typing import Optional

class KnowledgeBaseBase(BaseModel):
    name: str
    description: Optional[str] = None
    content: str

class KnowledgeBaseCreate(KnowledgeBaseBase):
    pass

class KnowledgeBaseUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    content: Optional[str] = None

class KnowledgeBase(KnowledgeBaseBase):
    id: int

    class Config:
        orm_mode = True
