from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from app.models import chat_message as models_chat_message
from app.schemas import chat_message as schemas_chat_message
from app.services import contact_service

def get_sessions_with_details(db: Session, agent_id: int, company_id: int):
    """
    Gets all unique sessions for an agent and includes details from the latest message
    of each session, such as status and assignee.
    """
    latest_message_subquery = db.query(
        models_chat_message.ChatMessage.session_id,
        func.max(models_chat_message.ChatMessage.id).label("max_id")
    ).filter(
        models_chat_message.ChatMessage.agent_id == agent_id,
        models_chat_message.ChatMessage.company_id == company_id
    ).group_by(models_chat_message.ChatMessage.session_id).subquery()

    latest_messages = db.query(models_chat_message.ChatMessage).join(
        latest_message_subquery,
        (models_chat_message.ChatMessage.id == latest_message_subquery.c.max_id)
    ).order_by(desc(models_chat_message.ChatMessage.timestamp)).all()

    return latest_messages

def get_first_message_for_session(db: Session, session_id: str, company_id: int):
    return db.query(models_chat_message.ChatMessage).filter(
        models_chat_message.ChatMessage.session_id == session_id,
        models_chat_message.ChatMessage.company_id == company_id
    ).order_by(models_chat_message.ChatMessage.timestamp).first()

def create_chat_message(db: Session, message: schemas_chat_message.ChatMessageCreate, agent_id: int, session_id: str, company_id: int, sender: str):
    
    # Get or create a contact for this session
    contact = contact_service.get_or_create_contact_by_session(db, session_id, company_id)
    
    db_message = models_chat_message.ChatMessage(
        message=message.message, 
        sender=sender, 
        agent_id=agent_id, 
        session_id=session_id, 
        company_id=company_id,
        message_type=message.message_type,
        contact_id=contact.id
    )
    db.add(db_message)
    db.commit()
    db.refresh(db_message)
    return db_message

def get_chat_messages(db: Session, agent_id: int, session_id: str, company_id: int, skip: int = 0, limit: int = 100):
    return db.query(models_chat_message.ChatMessage).filter(
        models_chat_message.ChatMessage.agent_id == agent_id,
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

def update_conversation_feedback(db: Session, session_id: str, feedback_rating: int, feedback_notes: str, company_id: int):
    db.query(models_chat_message.ChatMessage).filter(
        models_chat_message.ChatMessage.session_id == session_id,
        models_chat_message.ChatMessage.company_id == company_id
    ).update({"feedback_rating": feedback_rating, "feedback_notes": feedback_notes})
    db.commit()
    return True