from pydantic import BaseModel
import datetime

class ApiKeyBase(BaseModel):
    name: str

class ApiKeyCreate(ApiKeyBase):
    pass

class ApiKey(ApiKeyBase):
    id: int
    key: str
    company_id: int
    created_at: datetime.datetime

    class Config:
        orm_mode = True
