from sqlalchemy.orm import Session
from sqlalchemy import and_
from app.models.conversation_session import ConversationSession
from app.models.chat_message import ChatMessage
from app.schemas.conversation_session import ConversationSessionCreate, ConversationSessionUpdate

# Keywords that trigger a conversation restart
RESTART_KEYWORDS = ["0", "restart", "start over", "startover", "cancel", "reset", "start again"]


def _levenshtein_distance(s1: str, s2: str) -> int:
    """Calculate the Levenshtein distance between two strings."""
    if len(s1) < len(s2):
        return _levenshtein_distance(s2, s1)

    if len(s2) == 0:
        return len(s1)

    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row

    return previous_row[-1]


def _fuzzy_match_keyword(word: str, max_distance: int = 2) -> bool:
    """Check if a word fuzzy-matches any restart keyword."""
    word_lower = word.lower()
    for keyword in RESTART_KEYWORDS:
        # Skip "0" for fuzzy matching - it must be exact
        if keyword == "0":
            continue
        # Allow fuzzy match if distance is within threshold
        if _levenshtein_distance(word_lower, keyword) <= max_distance:
            return True
    return False

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

def get_session_by_contact_and_channel(db: Session, contact_id: int, channel: str, company_id: int):
    """
    Find an existing session by contact_id and channel.
    Returns the most recent active session for this contact on the specified channel.
    """
    return db.query(ConversationSession).filter(
        ConversationSession.contact_id == contact_id,
        ConversationSession.channel == channel,
        ConversationSession.company_id == company_id,
        ConversationSession.status.in_(['active', 'waiting_for_input', 'assigned'])
    ).order_by(ConversationSession.updated_at.desc()).first()

def update_session_context(db: Session, conversation_id: str, context: dict) -> ConversationSession:
    """
    Updates only the context field of a session.
    """
    db_session = db.query(ConversationSession).filter(
        ConversationSession.conversation_id == conversation_id
    ).first()

    if db_session:
        db_session.context = context
        db.commit()
        db.refresh(db_session)

    return db_session

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


def is_restart_command(message: str) -> bool:
    """
    Check if a message is a restart command.

    Supports:
    - Exact keyword match: "0", "restart", "cancel", "reset", "start over", "start again"
    - Keywords within sentences: "I want to cancel", "please restart"
    - Fuzzy matching for typos: "cancle" → "cancel", "restrat" → "restart"
    """
    if not message:
        return False

    message_lower = message.strip().lower()

    # 1. Exact match (single keyword)
    if message_lower in RESTART_KEYWORDS:
        return True

    # 2. Check if any keyword is contained within the message
    for keyword in RESTART_KEYWORDS:
        if keyword in message_lower:
            return True

    # 3. Fuzzy matching for single words or short messages
    words = message_lower.split()
    for word in words:
        # Clean punctuation from word
        clean_word = ''.join(c for c in word if c.isalnum())
        if clean_word and _fuzzy_match_keyword(clean_word):
            return True

    return False


async def reset_session_workflow(db: Session, session: ConversationSession, company_id: int) -> bool:
    """
    Reset workflow state for a session. Clears:
    - workflow_id
    - next_step_id
    - context
    - subworkflow_stack
    - Associated memories

    Args:
        db: Database session
        session: The conversation session to reset
        company_id: Company ID for looking up workflow

    Returns:
        True if reset was performed, False if no workflow was active.
    """
    from app.services import workflow_service, memory_service

    if not session.workflow_id and not session.next_step_id:
        return False  # Nothing to reset

    # Get agent_id before clearing workflow (needed to clear memories)
    # Prefer session.agent_id (the agent handling the conversation), fallback to workflow's first agent
    agent_id = session.agent_id
    if not agent_id and session.workflow_id:
        workflow = workflow_service.get_workflow(db, session.workflow_id, company_id)
        if workflow and workflow.agents:
            agent_id = workflow.agents[0].id

    # Clear session workflow state
    session.workflow_id = None
    session.next_step_id = None
    session.context = {}
    session.subworkflow_stack = None
    db.commit()
    db.refresh(session)

    # Clear memories if we had an agent
    if agent_id:
        memory_service.delete_all_memories(db, agent_id=agent_id, session_id=session.conversation_id)

    print(f"[conversation_session_service] 🔄 Session {session.conversation_id} workflow reset (agent_id={agent_id})")

    return True

