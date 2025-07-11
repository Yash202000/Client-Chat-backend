
from pydantic import BaseModel

class CompanySettingsBase(BaseModel):
    company_name: str
    support_email: str
    timezone: str
    language: str
    business_hours: bool

class CompanySettingsCreate(CompanySettingsBase):
    pass

class CompanySettingsUpdate(CompanySettingsBase):
    pass

class CompanySettings(CompanySettingsBase):
    id: int

    class Config:
        orm_mode = True
