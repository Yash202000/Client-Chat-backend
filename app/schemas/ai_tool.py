
from pydantic import BaseModel
from typing import Dict, List, Optional

class AIToolQuestionBase(BaseModel):
    question_text: str
    question_type: str
    hint: Optional[str] = None

class AIToolQuestionCreate(AIToolQuestionBase):
    pass

class AIToolQuestion(AIToolQuestionBase):
    id: int

    class Config:
        orm_mode = True

class AIToolBase(BaseModel):
    name: str
    description: Optional[str] = None

class AIToolCreate(AIToolBase):
    category_id: int
    questions: List[AIToolQuestionCreate] = []

class AITool(AIToolBase):
    id: int
    category_id: int
    likes: int
    views: int
    questions: List[AIToolQuestion] = []
    is_favorited: Optional[bool] = False

    class Config:
        orm_mode = True

class AIToolCategoryBase(BaseModel):
    name: str
    icon: Optional[str] = None

class AIToolCategoryCreate(AIToolCategoryBase):
    pass

class AIToolCategory(AIToolCategoryBase):
    id: int
    ai_tools: List[AITool] = []

    class Config:
        orm_mode = True

class ExecuteToolRequest(BaseModel):
    answers: Dict[str, str]
    language: str
