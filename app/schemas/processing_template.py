from pydantic import BaseModel
from typing import Optional

class ProcessingTemplateBase(BaseModel):
    name: str
    description: Optional[str] = None
    code: str

class ProcessingTemplateCreate(ProcessingTemplateBase):
    pass

class ProcessingTemplateUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    code: Optional[str] = None

class ProcessingTemplate(ProcessingTemplateBase):
    id: int
    company_id: int

    class Config:
        orm_mode = True
