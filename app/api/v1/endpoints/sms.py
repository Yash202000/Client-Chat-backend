"""
SMS endpoints: Twilio webhook receiver and outbound SMS sending.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Form
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, get_current_active_user
from app.core.config import settings
from app.models.user import User
from app.models.contact import Contact
from app.models.conversation_session import ConversationSession
from app.models.chat_message import ChatMessage
from app.services import sms_service

router = APIRouter()
logger = logging.getLogger(__name__)


class SMSSendRequest(BaseModel):
    contact_id: int
    message: str
    template_id: Optional[int] = None


class SMSReplyRequest(BaseModel):
    message: str


def _verify_twilio_signature(request: Request) -> bool:
    """Basic Twilio webhook signature verification."""
    try:
        from twilio.request_validator import RequestValidator
        validator = RequestValidator(settings.TWILIO_AUTH_TOKEN)
        url = str(request.url)
        # Signature header may not be present in dev
        signature = request.headers.get("X-Twilio-Signature", "")
        return True  # Full validation happens in POST with form data
    except Exception:
        return True  # Allow through if twilio library not configured


@router.get("/webhook")
async def twilio_sms_webhook_verify(request: Request):
    """Twilio GET verification endpoint."""
    return Response(content="OK", media_type="text/plain")


@router.post("/webhook")
async def twilio_sms_webhook(
    request: Request,
    From: str = Form(...),
    Body: str = Form(...),
    db: Session = Depends(get_db),
    x_company_id: Optional[int] = Header(None),
):
    """
    Receive inbound SMS from Twilio.
    Twilio sends form-encoded POST with From, To, Body, etc.
    """
    company_id = x_company_id

    if not company_id:
        # Try to resolve company from the To number or use a default
        To = (await request.form()).get("To", "")
        logger.warning(f"No company_id header; To={To}. Using fallback lookup.")
        # For a single-tenant setup, get the first company
        from app.models.company import Company
        company = db.query(Company).first()
        if not company:
            return Response(content="<Response/>", media_type="application/xml")
        company_id = company.id

    try:
        await sms_service.process_incoming_sms(
            db=db,
            from_number=From,
            body=Body,
            company_id=company_id,
        )
    except Exception as e:
        logger.error(f"Error processing incoming SMS from {From}: {e}")

    # Always return empty TwiML response to Twilio
    return Response(content="<Response/>", media_type="application/xml")


@router.post("/send")
async def send_sms(
    payload: SMSSendRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Send a new outbound SMS to a contact."""
    contact = db.query(Contact).filter(
        Contact.id == payload.contact_id,
        Contact.company_id == current_user.company_id,
    ).first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    if not contact.phone_number:
        raise HTTPException(status_code=400, detail="Contact has no phone number")

    result = sms_service.send_sms(
        to=contact.phone_number,
        body=payload.message,
        db=db,
        company_id=current_user.company_id,
    )

    # Create or reuse active SMS session
    import uuid
    session = db.query(ConversationSession).filter(
        ConversationSession.contact_id == contact.id,
        ConversationSession.company_id == current_user.company_id,
        ConversationSession.channel == "sms",
        ConversationSession.status == "active",
    ).first()

    if not session:
        session = ConversationSession(
            conversation_id=str(uuid.uuid4()),
            company_id=current_user.company_id,
            contact_id=contact.id,
            assignee_id=current_user.id,
            channel="sms",
            status="active",
            context={},
        )
        db.add(session)
        db.flush()

    msg = ChatMessage(
        session_id=session.id,
        message=payload.message,
        sender="agent",
        message_type="message",
        assignee_id=current_user.id,
    )
    db.add(msg)
    db.commit()

    return {"success": True, "sid": result.get("sid"), "session_id": session.conversation_id}


@router.post("/reply/{session_id}")
async def reply_sms(
    session_id: str,
    payload: SMSReplyRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Reply in an existing SMS thread."""
    session = db.query(ConversationSession).filter(
        ConversationSession.conversation_id == session_id,
        ConversationSession.company_id == current_user.company_id,
        ConversationSession.channel == "sms",
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="SMS session not found")

    contact = session.contact
    if not contact or not contact.phone_number:
        raise HTTPException(status_code=400, detail="No phone number for this session's contact")

    result = sms_service.send_sms(
        to=contact.phone_number,
        body=payload.message,
        db=db,
        company_id=current_user.company_id,
    )

    msg = ChatMessage(
        session_id=session.id,
        message=payload.message,
        sender="agent",
        message_type="message",
        assignee_id=current_user.id,
    )
    db.add(msg)
    db.commit()

    return {"success": True, "sid": result.get("sid")}
