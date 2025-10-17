
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, get_current_active_user
from app.models import user as models_user
from app.services import ai_chat_service
from app.schemas import ai_chat as schemas_ai_chat, chat_message as schemas_chat_message

router = APIRouter()

@router.post("/", response_model=schemas_chat_message.ChatMessage)
async def post_ai_chat(
    chat_request: schemas_ai_chat.AIChatRequest,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    return await ai_chat_service.handle_ai_chat(
        db=db, 
        chat_request=chat_request, 
        company_id=current_user.company_id, 
        user_id=current_user.id
    )
