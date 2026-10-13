from fastapi import APIRouter, Depends
from app.services import suggestion_service, notification_settings_service
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
    settings = notification_settings_service.get_notification_settings(db, company_id=current_user.company_id)
    if settings and not settings.suggested_replies_enabled:
        return SuggestionResponse(suggested_replies=[])

    replies = await suggestion_service.get_suggested_replies(db, current_user.company_id, request.conversation_history)
    return SuggestionResponse(suggested_replies=replies)
