
from pydantic import BaseModel
import datetime

from app.schemas.user import User

class CommentBase(BaseModel):
    content: str
    workflow_node_id: str

class CommentCreate(CommentBase):
    pass

class Comment(CommentBase):
    id: int
    user_id: int
    workflow_id: int
    user: User
    created_at: datetime.datetime

    class Config:
        orm_mode = True
