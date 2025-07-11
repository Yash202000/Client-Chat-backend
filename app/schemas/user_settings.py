
from pydantic import BaseModel

class UserSettingsBase(BaseModel):
    dark_mode: bool = False

class UserSettingsCreate(UserSettingsBase):
    pass

class UserSettingsUpdate(UserSettingsBase):
    pass

class UserSettings(UserSettingsBase):
    id: int
    user_id: int

    class Config:
        orm_mode = True
