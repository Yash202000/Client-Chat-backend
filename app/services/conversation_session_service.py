from sqlalchemy.orm import Session
from sqlalchemy import and_
from app.models.conversation_session import ConversationSession
from app.models.chat_message import ChatMessage
from app.schemas.conversation_session import ConversationSessionCreate, ConversationSessionUpdate

def get_session(db: Session, conversation_id: str) -> ConversationSession:
    """
    Retrieves a conversation session by its conversation_id.
    """
    return db.query(ConversationSession).filter(ConversationSession.conversation_id == conversation_id).first()

def get_sessions_by_status(db: Session, company_id: int, status: str, waiting_for_agent: bool = None) -> list[ConversationSession]:
    """
    Retrieves conversation sessions by status and optionally by waiting_for_agent flag.
    """
    query = db.query(ConversationSession).filter(
        and_(
            ConversationSession.company_id == company_id,
            ConversationSession.status == status
        )
    )

    if waiting_for_agent is not None:
        query = query.filter(ConversationSession.waiting_for_agent == waiting_for_agent)

    return query.all()

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
        update_data = session_update.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(db_session, key, value)
        db.commit()
        db.refresh(db_session)
    return db_session

def get_or_create_session(db: Session, conversation_id: str, workflow_id: int, contact_id: int, channel: str, company_id: int, agent_id: int = None):
    session = db.query(ConversationSession).filter(
        ConversationSession.conversation_id == conversation_id,
        ConversationSession.company_id == company_id
    ).first()

    if session:
        # If the session exists but has no workflow_id, update it.
        if session.workflow_id is None and workflow_id is not None:
            session.workflow_id = workflow_id
            db.commit()
            db.refresh(session)
        return session
    else:
        new_session = ConversationSession(
            conversation_id=conversation_id,
            workflow_id=workflow_id,
            contact_id=contact_id,
            channel=channel,
            company_id=company_id,
            agent_id=agent_id,
            status='active'
        )
        db.add(new_session)
        db.commit()
        db.refresh(new_session)
        return new_session


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

def get_session_by_conversation_id(db: Session, conversation_id: str, company_id: int):
    return db.query(ConversationSession).filter(
        ConversationSession.conversation_id == conversation_id,
        ConversationSession.company_id == company_id
    ).first()

async def update_session_connection_status(db: Session, conversation_id: str, is_connected: bool) -> ConversationSession:
    """
    Updates the session connection state and status based on client connection.
    - Updates is_client_connected field to track actual connection state
    - For non-assigned sessions: sets status to 'active' if connected, 'inactive' if disconnected
    - For assigned sessions: keeps status as 'assigned', only updates is_client_connected
    """
    from app.services.connection_manager import manager
    import json

    db_session = db.query(ConversationSession).filter(
        ConversationSession.conversation_id == conversation_id
    ).first()

    if db_session:
        old_connection_status = db_session.is_client_connected
        old_status = db_session.status

        # Always update the connection field
        db_session.is_client_connected = is_connected

        # Only update status if the session is not resolved, completed, closed, or assigned
        if db_session.status not in ['resolved', 'completed', 'closed', 'assigned']:
            new_status = 'active' if is_connected else 'inactive'
            db_session.status = new_status

        # Commit changes
        db.commit()
        db.refresh(db_session)

        # Log the change
        if old_connection_status != is_connected or old_status != db_session.status:
            print(f"[conversation_session_service] Updated session {conversation_id}:")
            print(f"  - Connection: {old_connection_status} -> {is_connected}")
            print(f"  - Status: {old_status} -> {db_session.status}")

            # Broadcast connection status change to all connected agents in the company
            status_update_message = json.dumps({
                "type": "session_status_update",
                "session_id": conversation_id,
                "status": db_session.status,
                "assignee_id": db_session.assignee_id,
                "is_client_connected": is_connected,
                "updated_at": db_session.updated_at.isoformat()
            })

            # Broadcast to company WebSocket channel
            if db_session.company_id:
                await manager.broadcast(status_update_message, str(db_session.company_id))

    return db_session


async def reopen_resolved_session(db: Session, session: ConversationSession, company_id: int) -> ConversationSession:
    """
    Reopens a resolved conversation session and notifies agents.

    Args:
        db: Database session
        session: The conversation session to reopen
        company_id: Company ID for broadcasting

    Returns:
        The updated session with status='active'
    """
    from app.services.connection_manager import manager
    import json

    if session.status != 'resolved':
        return session  # Already active or in another state

    old_status = session.status
    # If session has an assignee, reopen as 'assigned', otherwise as 'active'
    session.status = 'assigned' if session.assignee_id else 'active'
    db.commit()
    db.refresh(session)

    # Broadcast status change to company agents
    await manager.broadcast_to_company(
        company_id,
        json.dumps({
            "type": "session_reopened",
            "session_id": session.conversation_id,
            "status": session.status,  # Use actual status (assigned or active)
            "previous_status": old_status,
            "assignee_id": session.assignee_id,
            "updated_at": session.updated_at.isoformat()
        })
    )

    print(f"[conversation_session_service] 🔄 Session {session.conversation_id} reopened from {old_status} → {session.status}")

    return session

