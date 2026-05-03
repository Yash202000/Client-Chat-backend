"""
Outbound email endpoints: compose new email and reply in Gmail thread.
"""
import logging
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, get_current_active_user
from app.models.user import User
from app.models.contact import Contact
from app.models.conversation_session import ConversationSession
from app.models.chat_message import ChatMessage
from app.services import messaging_service, email_tracking_service

router = APIRouter()
logger = logging.getLogger(__name__)


class ComposeEmailRequest(BaseModel):
    to: List[str]                       # email addresses to send to
    subject: str
    body: str
    contact_id: Optional[int] = None    # primary contact for session linking
    deal_id: Optional[int] = None       # link email to a deal for tracking
    cc: Optional[List[str]] = None
    bcc: Optional[List[str]] = None
    track: bool = True                  # inject open/click tracking


class ReplyEmailRequest(BaseModel):
    body: str


@router.post("/compose")
async def compose_email(
    payload: ComposeEmailRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Send a new outbound email and create a ConversationSession."""
    if not payload.to:
        raise HTTPException(status_code=400, detail="At least one 'to' address is required")

    # Resolve primary contact for session linking
    contact = None
    if payload.contact_id:
        contact = db.query(Contact).filter(
            Contact.id == payload.contact_id,
            Contact.company_id == current_user.company_id,
        ).first()
    if contact is None:
        # Try to find by first To email
        contact = db.query(Contact).filter(
            Contact.email == payload.to[0],
            Contact.company_id == current_user.company_id,
        ).first()

    # Inject open pixel + click-tracking links when track=True
    send_body = payload.body
    open_token_id = None
    if payload.track:
        try:
            # Wrap plain text in minimal HTML if not already HTML
            html_body = send_body if send_body.strip().startswith('<') else f"<p>{send_body}</p>"
            html_body, _, open_token = email_tracking_service.inject_tracking(
                db=db,
                html_body=html_body,
                plain_body=send_body,
                subject=payload.subject,
                company_id=current_user.company_id,
                sent_by=current_user.id,
                contact_id=contact.id if contact else None,
                deal_id=payload.deal_id,
            )
            send_body = html_body
            open_token_id = open_token.token
        except Exception as exc:
            logger.warning(f"Tracking injection failed (continuing without tracking): {exc}")

    try:
        result = await messaging_service.send_gmail_message(
            to=payload.to,
            subject=payload.subject,
            body=send_body,
            thread_id=None,
            db=db,
            company_id=current_user.company_id,
            cc=payload.cc,
            bcc=payload.bcc,
        )
    except Exception as e:
        logger.error(f"Failed to send email to {payload.to}: {e}")
        raise HTTPException(status_code=502, detail=f"Failed to send email: {str(e)}")

    gmail_thread_id = result.get("threadId") if result else None

    # Create ConversationSession for this email thread
    session = ConversationSession(
        conversation_id=str(uuid.uuid4()),
        company_id=current_user.company_id,
        contact_id=contact.id if contact else None,
        assignee_id=current_user.id,
        channel="gmail",
        status="active",
        context={
            "subject": payload.subject,
            "gmail_thread_id": gmail_thread_id,
            "to": payload.to,
            "cc": payload.cc or [],
            "bcc": payload.bcc or [],
        },
    )
    db.add(session)
    db.flush()

    msg = ChatMessage(
        session_id=session.id,
        message=payload.body,
        sender="agent",
        message_type="message",
        assignee_id=current_user.id,
    )
    db.add(msg)
    db.commit()

    return {"success": True, "session_id": session.conversation_id, "thread_id": gmail_thread_id, "tracking_token": open_token_id}


@router.post("/reply/{session_id}")
async def reply_email(
    session_id: str,
    payload: ReplyEmailRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Reply in an existing Gmail thread."""
    session = db.query(ConversationSession).filter(
        ConversationSession.conversation_id == session_id,
        ConversationSession.company_id == current_user.company_id,
        ConversationSession.channel == "gmail",
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Email session not found")

    contact = session.contact
    if not contact or not contact.email:
        raise HTTPException(status_code=400, detail="No email address for this session's contact")

    context = session.context or {}
    gmail_thread_id = context.get("gmail_thread_id")
    subject = context.get("subject", "Re: ")

    try:
        result = await messaging_service.send_gmail_message(
            to=contact.email,
            subject=f"Re: {subject}" if not subject.startswith("Re:") else subject,
            body=payload.body,
            thread_id=gmail_thread_id,
            db=db,
            company_id=current_user.company_id,
        )
    except Exception as e:
        logger.error(f"Failed to send email reply for session {session_id}: {e}")
        raise HTTPException(status_code=502, detail=f"Failed to send email: {str(e)}")

    msg = ChatMessage(
        session_id=session.id,
        message=payload.body,
        sender="agent",
        message_type="message",
        assignee_id=current_user.id,
    )
    db.add(msg)
    db.commit()

    return {"success": True}
