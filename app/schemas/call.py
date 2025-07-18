from pydantic import BaseModel

class StartCallRequest(BaseModel):
    session_id: str
