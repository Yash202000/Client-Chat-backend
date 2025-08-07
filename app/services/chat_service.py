from sqlalchemy.orm import Session
from sqlalchemy import func, desc, or_
from app.models import chat_message as models_chat_message, conversation_session as models_conversation_session, contact as models_contact
from app.schemas import chat_message as schemas_chat_message
from app.services import contact_service

def get_sessions_with_details(db: Session, company_id: int, agent_id: int = None, status: str = None):
    """
    Gets all unique sessions for a company, optionally filtered by agent or status.
    It retrieves the latest message for ordering and context.
    """
    query = db.query(models_conversation_session.ConversationSession).filter(
        models_conversation_session.ConversationSession.company_id == company_id
    )

    if agent_id:
        query = query.filter(models_conversation_session.ConversationSession.agent_id == agent_id)
    
    if status:
        query = query.filter(models_conversation_session.ConversationSession.status == status)

    # Order by the most recently updated session
    sessions = query.order_by(desc(models_conversation_session.ConversationSession.updated_at)).all()
    return sessions

def get_contact_for_session(db: Session, session_id: str, company_id: int):
    """
    Retrieves the contact associated with a given session.
    """
    session = db.query(models_conversation_session.ConversationSession).filter(
        models_conversation_session.ConversationSession.conversation_id == session_id,
        models_conversation_session.ConversationSession.company_id == company_id
    ).first()
    
    if session:
        return session.contact
    return None


def get_first_message_for_session(db: Session, session_id: str, company_id: int):
    return db.query(models_chat_message.ChatMessage).filter(
        models_chat_message.ChatMessage.session_id == session_id,
        models_chat_message.ChatMessage.company_id == company_id
    ).order_by(models_chat_message.ChatMessage.timestamp).first()

def create_chat_message(db: Session, message: schemas_chat_message.ChatMessageCreate, agent_id: int, session_id: str, company_id: int, sender: str):
    
    # Get the session to retrieve the contact_id
    session = db.query(models_conversation_session.ConversationSession).filter(
        models_conversation_session.ConversationSession.conversation_id == session_id,
        models_conversation_session.ConversationSession.company_id == company_id
    ).first()

    if not session or not session.contact_id:
        raise ValueError(f"Session {session_id} not found or has no associated contact.")
    
    db_message = models_chat_message.ChatMessage(
        message=message.message, 
        sender=sender, 
        agent_id=agent_id, 
        session_id=session_id, 
        company_id=company_id,
        message_type=message.message_type,
        token=message.token, # Add the token here
        contact_id=session.contact_id
    )
    db.add(db_message)
    db.commit()
    db.refresh(db_message)
    return db_message

def get_chat_messages(db: Session, agent_id: int, session_id: str, company_id: int, skip: int = 0, limit: int = 100):
    return db.query(models_chat_message.ChatMessage).filter(
        or_(models_chat_message.ChatMessage.agent_id == agent_id, models_chat_message.ChatMessage.agent_id == None),
        models_chat_message.ChatMessage.session_id == session_id,
        models_chat_message.ChatMessage.company_id == company_id
    ).order_by(models_chat_message.ChatMessage.timestamp).offset(skip).limit(limit).all()

def update_conversation_status(db: Session, session_id: str, status: str, company_id: int):
    db.query(models_chat_message.ChatMessage).filter(
        models_chat_message.ChatMessage.session_id == session_id,
        models_chat_message.ChatMessage.company_id == company_id
    ).update({"status": status})
    db.commit()
    return True

def update_conversation_assignee(db: Session, session_id: str, user_id: int, company_id: int):
    db.query(models_chat_message.ChatMessage).filter(
        models_chat_message.ChatMessage.session_id == session_id,
        models_chat_message.ChatMessage.company_id == company_id
    ).update({"status": "assigned", "assignee_id": user_id})
    db.commit()
    return True

from app.core.websockets import manager
import json

async def send_proactive_message(db: Session, session_id: str, message_text: str):
    """
    Sends a proactive message to a user in a specific session.
    """
    # Note: Proactive messages are sent from the "agent"
    # We can enhance this later to allow specifying the sender.
    message_data = {"message": message_text, "message_type": "message", "sender": "agent"}
    await manager.broadcast_to_session(session_id, json.dumps(message_data), sender_type='agent')
