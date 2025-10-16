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


def get_session_details(db: Session, company_id: int, agent_id: int = None, broadcast_session_id: str = None,  status: str = None):
    """
    Gets session details by conversation_id for a company.
    Note: agent_id is kept for backward compatibility but not used in filtering
    since conversations can be viewed across different agents.
    """
    session = db.query(models_conversation_session.ConversationSession).filter(
        models_conversation_session.ConversationSession.conversation_id == str(broadcast_session_id),
        models_conversation_session.ConversationSession.company_id == company_id
    ).first()

    return session


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
    
    # issue = None
    # if sender == 'user':
    #     issue = tag_issue(message.message)

    db_message = models_chat_message.ChatMessage(
        message=message.message, 
        sender=sender, 
        agent_id=agent_id, 
        session_id=session.id,
        company_id=company_id,
        message_type=message.message_type,
        token=message.token, # Add the token here
        contact_id=session.contact_id,
        # issue=issue
    )
    db.add(db_message)
    db.commit()
    db.refresh(db_message)
    return db_message

def get_chat_messages(db: Session, agent_id: int, session_id: str, company_id: int, skip: int = 0, limit: int = 100):
    session = db.query(models_conversation_session.ConversationSession).filter(
        models_conversation_session.ConversationSession.conversation_id == session_id,
        models_conversation_session.ConversationSession.company_id == company_id
    ).first()

    if session:
        # Return all messages for this session regardless of which agent created them
        # This allows viewing conversations across different agents in the same company
        return db.query(models_chat_message.ChatMessage).filter(
            models_chat_message.ChatMessage.session_id == session.id,
            models_chat_message.ChatMessage.company_id == company_id
        ).order_by(models_chat_message.ChatMessage.timestamp).offset(skip).limit(limit).all()
    # else return null
    return []

async def update_conversation_status(db: Session, session_id: str, status: str, company_id: int):
    """
    Updates the status of a conversation session (e.g., 'resolved', 'active', 'pending').
    """
    from app.core.websockets import manager
    import json

    db.query(models_conversation_session.ConversationSession).filter(
        models_conversation_session.ConversationSession.conversation_id == session_id,
        models_conversation_session.ConversationSession.company_id == company_id
    ).update({"status": status})
    db.commit()

    # Broadcast status change to all connected agents in real-time
    status_update_message = json.dumps({
        "type": "session_status_update",
        "session_id": session_id,
        "status": status
    })
    await manager.broadcast(status_update_message, str(company_id))

    return True

async def update_conversation_assignee(db: Session, session_id: str, user_id: int, company_id: int):
    """
    Assigns a conversation to a user and updates the session status to 'assigned'.
    """
    from app.core.websockets import manager
    import json

    db.query(models_conversation_session.ConversationSession).filter(
        models_conversation_session.ConversationSession.conversation_id == session_id,
        models_conversation_session.ConversationSession.company_id == company_id
    ).update({"status": "assigned", "assignee_id": user_id})
    db.commit()

    # Broadcast status change to all connected agents in real-time
    status_update_message = json.dumps({
        "type": "session_status_update",
        "session_id": session_id,
        "status": "assigned"
    })
    await manager.broadcast(status_update_message, str(company_id))

    return True

async def send_proactive_message(db: Session, session_id: str, message_text: str):
    """
    Sends a proactive message to a user in a specific session.
    """
    # Note: Proactive messages are sent from the "agent"
    # We can enhance this later to allow specifying the sender.
    message_data = {"message": message_text, "message_type": "message", "sender": "agent"}
    await manager.broadcast_to_session(session_id, json.dumps(message_data), sender_type='agent')
