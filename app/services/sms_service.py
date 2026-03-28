import logging
import uuid
from typing import Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.contact import Contact
from app.models.conversation_session import ConversationSession
from app.models.chat_message import ChatMessage

logger = logging.getLogger(__name__)


def send_sms(to: str, body: str, db: Session, company_id: int) -> dict:
    """Send an SMS via Twilio."""
    try:
        from twilio.rest import Client as TwilioClient
        client = TwilioClient(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        message = client.messages.create(
            body=body,
            from_=settings.TWILIO_PHONE_NUMBER,
            to=to,
        )
        logger.info(f"SMS sent to {to}, SID: {message.sid}")
        return {"sid": message.sid, "status": message.status}
    except Exception as e:
        logger.error(f"Failed to send SMS to {to}: {e}")
        raise


async def process_incoming_sms(
    db: Session,
    from_number: str,
    body: str,
    company_id: int,
    agent_id: Optional[int] = None,
) -> None:
    """
    Process an inbound SMS:
    1. Get or create contact by phone number
    2. Get or create/reopen ConversationSession (channel='sms')
    3. Save incoming ChatMessage
    4. Trigger agent response
    """
    # 1. Get or create contact
    contact = db.query(Contact).filter(
        Contact.phone_number == from_number,
        Contact.company_id == company_id,
    ).first()

    if not contact:
        contact = Contact(
            phone_number=from_number,
            name=from_number,
            company_id=company_id,
        )
        db.add(contact)
        db.flush()

    # 2. Get active SMS session or create one
    session = db.query(ConversationSession).filter(
        ConversationSession.contact_id == contact.id,
        ConversationSession.company_id == company_id,
        ConversationSession.channel == "sms",
        ConversationSession.status == "active",
    ).first()

    if not session:
        conversation_id = str(uuid.uuid4())
        session = ConversationSession(
            conversation_id=conversation_id,
            company_id=company_id,
            contact_id=contact.id,
            agent_id=agent_id,
            channel="sms",
            status="active",
            context={},
        )
        db.add(session)
        db.flush()
    elif session.status in ("resolved", "archived"):
        # Reopen resolved session
        session.status = "active"
        import datetime
        session.last_reopened_at = datetime.datetime.utcnow()
        session.reopen_count = (session.reopen_count or 0) + 1
        db.flush()

    # 3. Save incoming message
    incoming_msg = ChatMessage(
        session_id=session.id,
        contact_id=contact.id,
        message=body,
        sender="user",
        message_type="message",
    )
    db.add(incoming_msg)
    db.commit()

    # 4. Trigger agent response
    try:
        from app.services import agent_execution_service
        response_text = await agent_execution_service.generate_agent_response(
            db=db,
            session=session,
            user_message=body,
            company_id=company_id,
        )
        if response_text:
            send_sms(to=from_number, body=response_text, db=db, company_id=company_id)

            # Save agent response message
            agent_msg = ChatMessage(
                session_id=session.id,
                agent_id=session.agent_id,
                message=response_text,
                sender="agent",
                message_type="message",
            )
            db.add(agent_msg)
            db.commit()
    except Exception as e:
        logger.error(f"Error generating agent response for SMS session {session.conversation_id}: {e}")
