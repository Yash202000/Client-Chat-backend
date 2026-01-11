"""
API Channel Endpoints

External-facing API for third-party integrations.
Authenticated via X-API-Key header.
"""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status, Header, Query, Body
from sqlalchemy.orm import Session
from typing import Optional, Tuple

from app.core.dependencies import get_db
from app.models.api_key import ApiKey
from app.models.api_integration import ApiIntegration
from app.services import api_key_service, conversation_session_service, chat_service
from app.services.api_channel_service import (
    ApiChannelService,
    get_api_integration_by_api_key
)
from app.schemas.api_channel import (
    ApiMessageSend, ApiMessageResponse, ResponseMode,
    ApiSessionCreate, ApiSession, ApiSessionClose,
    ApiMessageList, ApiMessageItem, ApiStatusResponse
)
from app.services import contact_service

router = APIRouter()


async def get_api_key_and_integration(
    x_api_key: str = Header(..., alias="X-API-Key"),
    db: Session = Depends(get_db)
) -> Tuple[ApiKey, ApiIntegration, int]:
    """
    Validate API key and get associated integration.
    Returns tuple of (api_key, api_integration, company_id)
    """
    api_key = api_key_service.get_api_key_by_key(db, key=x_api_key)
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key"
        )

    # Check if key is active (if the field exists)
    if hasattr(api_key, 'is_active') and not api_key.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key is inactive"
        )

    # Check if key is expired (if the field exists)
    if hasattr(api_key, 'expires_at') and api_key.expires_at:
        if api_key.expires_at < datetime.now(timezone.utc):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="API key has expired"
            )

    # Update last used timestamp
    if hasattr(api_key, 'last_used_at'):
        api_key.last_used_at = datetime.now(timezone.utc)
        db.commit()

    integration = get_api_integration_by_api_key(db, api_key)
    if not integration:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No API integration configured for this key. Create one first via the management API."
        )

    if not integration.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="API integration is disabled"
        )

    return api_key, integration, api_key.company_id


# ============ MESSAGE ENDPOINTS ============

@router.post("/message", response_model=ApiMessageResponse)
async def send_message(
    message: ApiMessageSend,
    db: Session = Depends(get_db),
    auth_data: Tuple[ApiKey, ApiIntegration, int] = Depends(get_api_key_and_integration)
):
    """
    Send a message to the AI agent and receive a response.

    - Supports sync (wait for response) or async (webhook callback) modes
    - Automatically creates or continues conversation sessions
    - Executes configured workflows or falls back to agent

    **Request Body:**
    - `external_user_id`: Your unique identifier for the user
    - `message`: The message content
    - `response_mode`: "sync" (default) or "async"
    - `workflow_id`: (optional) Override default workflow
    - `agent_id`: (optional) Override default agent
    - `context`: (optional) Additional context variables
    - `metadata`: (optional) Pass-through data returned in response
    """
    api_key, integration, company_id = auth_data

    # Process message
    service = ApiChannelService(db)
    response = await service.process_message(
        message_data=message,
        api_integration=integration,
        company_id=company_id
    )

    return response


@router.get("/messages/{session_id}", response_model=ApiMessageList)
async def get_messages(
    session_id: str,
    limit: int = Query(default=50, le=100, description="Max messages to return"),
    before_id: Optional[int] = Query(default=None, description="Get messages before this ID"),
    db: Session = Depends(get_db),
    auth_data: Tuple[ApiKey, ApiIntegration, int] = Depends(get_api_key_and_integration)
):
    """
    Get messages from a conversation session.

    Supports cursor-based pagination via `before_id`.
    Messages are returned in chronological order (oldest first).
    """
    api_key, integration, company_id = auth_data

    # Verify session belongs to this company
    session = conversation_session_service.get_session_by_conversation_id(
        db, session_id, company_id
    )
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found"
        )

    messages = chat_service.get_chat_messages(
        db,
        agent_id=None,
        session_id=session_id,
        company_id=company_id,
        limit=limit + 1,  # Get one extra to check has_more
        before_id=before_id
    )

    has_more = len(messages) > limit
    if has_more:
        messages = messages[:limit]

    return ApiMessageList(
        session_id=session_id,
        messages=[
            ApiMessageItem(
                id=m.id,
                message=m.message,
                sender=m.sender,
                message_type=m.message_type,
                attachments=m.attachments,
                options=m.options,
                timestamp=m.timestamp
            ) for m in messages
        ],
        has_more=has_more,
        next_cursor=messages[0].id if messages and has_more else None
    )


# ============ SESSION ENDPOINTS ============

@router.post("/sessions", response_model=ApiSession, status_code=status.HTTP_201_CREATED)
async def create_session(
    session_data: ApiSessionCreate,
    db: Session = Depends(get_db),
    auth_data: Tuple[ApiKey, ApiIntegration, int] = Depends(get_api_key_and_integration)
):
    """
    Create a new conversation session explicitly.

    Sessions are auto-created on first message, but this allows
    pre-creating sessions with specific context.
    """
    api_key, integration, company_id = auth_data

    # Get or create contact
    contact = contact_service.get_or_create_contact_for_channel(
        db,
        company_id=company_id,
        channel='api',
        channel_identifier=session_data.external_user_id,
        name=session_data.name
    )

    conversation_id = f"api_{company_id}_{session_data.external_user_id}"

    session = conversation_session_service.get_or_create_session(
        db,
        conversation_id=conversation_id,
        workflow_id=integration.default_workflow_id,
        contact_id=contact.id,
        channel='api',
        company_id=company_id,
        agent_id=integration.default_agent_id
    )

    # Apply any initial context
    if session_data.context:
        current_context = session.context or {}
        current_context.update(session_data.context)
        session.context = current_context
        db.commit()
        db.refresh(session)

    return ApiSession(
        session_id=session.conversation_id,
        external_user_id=session_data.external_user_id,
        status=session.status,
        is_ai_enabled=session.is_ai_enabled,
        workflow_id=session.workflow_id,
        agent_id=session.agent_id,
        context=session.context or {},
        created_at=session.created_at,
        updated_at=session.updated_at
    )


@router.get("/sessions/{session_id}", response_model=ApiSession)
async def get_session(
    session_id: str,
    db: Session = Depends(get_db),
    auth_data: Tuple[ApiKey, ApiIntegration, int] = Depends(get_api_key_and_integration)
):
    """Get session details."""
    api_key, integration, company_id = auth_data

    session = conversation_session_service.get_session_by_conversation_id(
        db, session_id, company_id
    )
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found"
        )

    # Extract external_user_id from session_id (format: api_{company_id}_{external_user_id})
    parts = session_id.split("_", 2)
    external_user_id = parts[2] if len(parts) > 2 else ""

    return ApiSession(
        session_id=session.conversation_id,
        external_user_id=external_user_id,
        status=session.status,
        is_ai_enabled=session.is_ai_enabled,
        workflow_id=session.workflow_id,
        agent_id=session.agent_id,
        context=session.context or {},
        created_at=session.created_at,
        updated_at=session.updated_at
    )


@router.post("/sessions/{session_id}/close", response_model=ApiStatusResponse)
async def close_session(
    session_id: str,
    close_data: Optional[ApiSessionClose] = Body(default=None),
    db: Session = Depends(get_db),
    auth_data: Tuple[ApiKey, ApiIntegration, int] = Depends(get_api_key_and_integration)
):
    """Close/resolve a conversation session."""
    api_key, integration, company_id = auth_data

    session = conversation_session_service.get_session_by_conversation_id(
        db, session_id, company_id
    )
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found"
        )

    # Update session status
    session.status = "resolved"
    session.resolved_at = datetime.now(timezone.utc)
    if close_data and close_data.resolution_notes:
        context = session.context or {}
        context["resolution_notes"] = close_data.resolution_notes
        session.context = context
    db.commit()

    return ApiStatusResponse(
        status="resolved",
        message=f"Session {session_id} has been closed"
    )


@router.post("/sessions/{session_id}/ai", response_model=ApiStatusResponse)
async def toggle_ai(
    session_id: str,
    enabled: bool = Query(..., description="Enable or disable AI responses"),
    db: Session = Depends(get_db),
    auth_data: Tuple[ApiKey, ApiIntegration, int] = Depends(get_api_key_and_integration)
):
    """Enable or disable AI responses for a session."""
    api_key, integration, company_id = auth_data

    session = conversation_session_service.toggle_ai_for_session(
        db, session_id, company_id, enabled
    )
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found"
        )

    return ApiStatusResponse(
        status="success",
        message=f"AI {'enabled' if enabled else 'disabled'} for session {session_id}"
    )


@router.post("/sessions/{session_id}/context", response_model=ApiStatusResponse)
async def update_session_context(
    session_id: str,
    context: dict,
    db: Session = Depends(get_db),
    auth_data: Tuple[ApiKey, ApiIntegration, int] = Depends(get_api_key_and_integration)
):
    """Update context variables for a session."""
    api_key, integration, company_id = auth_data

    session = conversation_session_service.get_session_by_conversation_id(
        db, session_id, company_id
    )
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found"
        )

    # Merge new context with existing
    current_context = session.context or {}
    current_context.update(context)
    session.context = current_context
    db.commit()

    return ApiStatusResponse(
        status="success",
        message="Session context updated"
    )
