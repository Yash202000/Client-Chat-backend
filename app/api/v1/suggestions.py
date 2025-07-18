from fastapi import APIRouter, Depends
from app.services import suggestion_service
from app.schemas.suggestion import SuggestionRequest, SuggestionResponse

router = APIRouter()

@router.post("/suggest-replies", response_model=SuggestionResponse)
async def suggest_replies(request: SuggestionRequest):
    replies = await suggestion_service.get_suggested_replies(request.conversation_history)
    return SuggestionResponse(suggested_replies=replies)
