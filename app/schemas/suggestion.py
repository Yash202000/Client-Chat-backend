from pydantic import BaseModel
from typing import List

class SuggestionRequest(BaseModel):
    conversation_history: List[str]

class SuggestionResponse(BaseModel):
    suggested_replies: List[str]
