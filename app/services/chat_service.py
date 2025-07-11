from sqlalchemy.orm import Session
from app.models import chat_message as models_chat_message
from app.schemas import chat_message as schemas_chat_message

def create_chat_message(db: Session, message: schemas_chat_message.ChatMessageCreate, agent_id: int, session_id: str, company_id: int, sender: str):
    db_message = models_chat_message.ChatMessage(**message.dict(), agent_id=agent_id, session_id=session_id, company_id=company_id)
    db.add(db_message)
    db.commit()
    db.refresh(db_message)
    return db_message

def get_chat_messages(db: Session, agent_id: int, session_id: str, company_id: int, skip: int = 0, limit: int = 100):
    return db.query(models_chat_message.ChatMessage).filter(
        models_chat_message.ChatMessage.agent_id == agent_id,
        models_chat_message.ChatMessage.session_id == session_id,
        models_chat_message.ChatMessage.company_id == company_id
    ).offset(skip).limit(limit).all()
