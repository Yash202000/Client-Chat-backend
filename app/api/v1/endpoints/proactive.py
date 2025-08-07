from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.core.dependencies import get_db, get_current_company_from_api_key
from app.schemas.proactive_message import ProactiveMessageCreate
from app.services import conversation_session_service, chat_service, contact_service
from app.models.company import Company

router = APIRouter()

@router.post("/message", status_code=status.HTTP_202_ACCEPTED)
async def send_proactive_message(
    proactive_message: ProactiveMessageCreate,
    db: Session = Depends(get_db),
    company: Company = Depends(get_current_company_from_api_key),
):
    if not proactive_message.contact_id and not proactive_message.session_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either contact_id or session_id must be provided.",
        )

    session = None
    if proactive_message.session_id:
        session = conversation_session_service.get_session(db, proactive_message.session_id)
    elif proactive_message.contact_id:
        contact = contact_service.get_contact(db, proactive_message.contact_id, company.id)
        if contact:
            session = conversation_session_service.get_or_create_session(db, contact.id)

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Could not find or create a conversation session.",
        )

    await chat_service.send_proactive_message(
        db=db,
        session_id=session.conversation_id,
        message_text=proactive_message.text,
    )

    return {"message": "Message accepted for delivery."}
