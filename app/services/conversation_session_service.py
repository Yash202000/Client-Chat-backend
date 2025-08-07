from sqlalchemy.orm import Session
from app.models.conversation_session import ConversationSession
from app.models.chat_message import ChatMessage
from app.schemas.conversation_session import ConversationSessionCreate, ConversationSessionUpdate

def get_session(db: Session, conversation_id: str) -> ConversationSession:
    """
    Retrieves a conversation session by its conversation_id.
    """
    return db.query(ConversationSession).filter(ConversationSession.conversation_id == conversation_id).first()

def get_chat_history(db: Session, conversation_id: str, limit: int = 20) -> list[ChatMessage]:
    """
    Retrieves the chat history for a given conversation_id.
    """
    return db.query(ChatMessage).filter(ChatMessage.session_id == conversation_id).order_by(ChatMessage.timestamp.asc()).limit(limit).all()

def create_session(db: Session, session: ConversationSessionCreate) -> ConversationSession:
    """
    Creates a new conversation session.
    """
    print(f"Attempting to create session with data: {session.dict()}")
    db_session = ConversationSession(**session.dict())
    try:
        db.add(db_session)
        db.commit()
        db.refresh(db_session)
        print(f"Session created and refreshed: {db_session.__dict__}")
    except Exception as e:
        db.rollback()
        print(f"Error creating session: {e}")
        raise
    return db_session

def update_session(db: Session, conversation_id: str, session_update: ConversationSessionUpdate) -> ConversationSession:
    """
    Updates an existing conversation session.
    """
    db_session = get_session(db, conversation_id)
    if db_session:
        update_data = session_update.dict(exclude_unset=True)
        for key, value in update_data.items():
            setattr(db_session, key, value)
        db.commit()
        db.refresh(db_session)
    return db_session

def get_or_create_session(db: Session, conversation_id: str, workflow_id: int, contact_id: int, channel: str, company_id: int, agent_id: int = None) -> ConversationSession:
    """
    Gets a session by conversation_id. If not found, creates a new one.
    """
    # 1. Try to get the session by its unique conversation_id
    db_session = db.query(ConversationSession).filter(
        ConversationSession.conversation_id == conversation_id
    ).first()

    if db_session:
        return db_session

    # 2. If no session found with that conversation_id, create a new one
    session_create = ConversationSessionCreate(
        conversation_id=conversation_id,
        workflow_id=workflow_id,
        contact_id=contact_id,
        channel=channel,
        status='active',
        company_id=company_id,
        agent_id=agent_id
    )
    return create_session(db, session_create)


def toggle_ai_for_session(db: Session, conversation_id: str, company_id: int, is_enabled: bool) -> ConversationSession:
    """
    Updates the is_ai_enabled flag for a specific conversation session.
    """
    db_session = db.query(ConversationSession).filter(
        ConversationSession.conversation_id == conversation_id,
        ConversationSession.company_id == company_id
    ).first()

    if db_session:
        db_session.is_ai_enabled = is_enabled
        db.commit()
        db.refresh(db_session)
    
    return db_session
