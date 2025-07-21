from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional

from app.core.dependencies import get_db
from app.schemas import optimization_suggestion as schemas_optimization_suggestion
from app.services import optimization_service
from app.core.auth import get_current_user
from app.models.user import User

router = APIRouter()

@router.post("/generate-suggestions", response_model=List[schemas_optimization_suggestion.OptimizationSuggestion], status_code=status.HTTP_201_CREATED)
async def generate_suggestions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    agent_id: Optional[int] = None
):
    # This endpoint triggers the LLM-powered suggestion generation
    # In a real application, this might be a long-running task triggered asynchronously
    try:
        suggestions = await optimization_service.generate_suggestions_from_llm(db, current_user.company_id, agent_id)
        return suggestions
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate suggestions: {e}")

@router.get("/suggestions", response_model=List[schemas_optimization_suggestion.OptimizationSuggestion])
def get_suggestions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    agent_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 100
):
    # This endpoint retrieves previously generated suggestions
    suggestions = optimization_service.get_optimization_suggestions(db, current_user.company_id, skip=skip, limit=limit)
    # Filter by agent_id if provided
    if agent_id:
        suggestions = [s for s in suggestions if s.agent_id == agent_id]
    return suggestions
