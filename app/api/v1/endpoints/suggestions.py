from fastapi import APIRouter, Depends
from app.services import suggestion_service
from app.schemas.suggestion import SuggestionRequest, SuggestionResponse
from app.core.dependencies import get_db
from sqlalchemy.orm import Session
from app.core.auth import get_current_user
from app.models.user import User

router = APIRouter()

@router.post("/suggest-replies", response_model=SuggestionResponse)
async def suggest_replies(
    request: SuggestionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    replies = await suggestion_service.get_suggested_replies(db, current_user.company_id, request.conversation_history)
    return SuggestionResponse(suggested_replies=replies)
