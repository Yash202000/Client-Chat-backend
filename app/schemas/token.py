from typing import Optional

from pydantic import BaseModel


class Token(BaseModel):
    access_token: str
    token_type: str
    company_id: int


class TokenData(BaseModel):
    email: Optional[str] = None
