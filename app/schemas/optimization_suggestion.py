from pydantic import BaseModel
from typing import Optional, Dict, Any
import datetime

class OptimizationSuggestionBase(BaseModel):
    suggestion_type: str # e.g., 'prompt_refinement', 'knowledge_base_gap', 'new_tool_recommendation'
    description: str
    agent_id: Optional[int] = None
    details: Optional[Dict[str, Any]] = None # Additional context, e.g., problematic queries

class OptimizationSuggestionCreate(OptimizationSuggestionBase):
    pass

class OptimizationSuggestion(OptimizationSuggestionBase):
    id: int
    company_id: int
    created_at: datetime.datetime

    class Config:
        orm_mode = True
