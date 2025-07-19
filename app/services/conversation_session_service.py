from sqlalchemy.orm import Session
from app.models.conversation_session import ConversationSession
from app.schemas.conversation_session import ConversationSessionCreate, ConversationSessionUpdate

def get_session(db: Session, conversation_id: str) -> ConversationSession:
    """
    Retrieves a conversation session by its conversation_id.
    """
    return db.query(ConversationSession).filter(ConversationSession.conversation_id == conversation_id).first()

def create_session(db: Session, session: ConversationSessionCreate) -> ConversationSession:
    """
    Creates a new conversation session.
    """
    db_session = ConversationSession(**session.dict())
    db.add(db_session)
    db.commit()
    db.refresh(db_session)
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

def get_or_create_session(db: Session, conversation_id: str, workflow_id: int) -> ConversationSession:
    """
    Gets a session if it exists, otherwise creates a new one.
    """
    db_session = get_session(db, conversation_id)
    if not db_session:
        session_create = ConversationSessionCreate(
            conversation_id=conversation_id,
            workflow_id=workflow_id
        )
        db_session = create_session(db, session_create)
    return db_session
