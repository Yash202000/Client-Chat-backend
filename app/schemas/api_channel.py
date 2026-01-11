from pydantic import BaseModel, Field, HttpUrl
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


class ResponseMode(str, Enum):
    """How the API should deliver responses"""
    SYNC = "sync"    # Wait for response in same HTTP request
    ASYNC = "async"  # Return immediately, webhook callback later


# ============ MESSAGE SCHEMAS ============

class ApiMessageSend(BaseModel):
    """Request to send a message via API channel"""
    external_user_id: str = Field(..., description="Third-party's user identifier")
    message: str = Field(..., description="Message content")
    message_type: str = Field(default="text", description="Type of message")
    attachments: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="File attachments with url, name, type, size"
    )
    context: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Additional context variables to pass to workflow"
    )
    response_mode: ResponseMode = Field(
        default=ResponseMode.SYNC,
        description="How to deliver the response"
    )
    workflow_id: Optional[int] = Field(
        default=None,
        description="Override default workflow for this message"
    )
    agent_id: Optional[int] = Field(
        default=None,
        description="Override default agent for this message"
    )
    metadata: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Pass-through metadata returned in response"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "external_user_id": "user_12345",
                "message": "Hello, I need help with my order",
                "response_mode": "sync",
                "metadata": {"source": "mobile_app"}
            }
        }


class ApiMessageResponse(BaseModel):
    """Response from API channel"""
    session_id: str = Field(..., description="Conversation session ID")
    message_id: int = Field(..., description="ID of the saved message")
    response_message: Optional[str] = Field(
        default=None,
        description="Agent/workflow response text (combined if multiple messages)"
    )
    response_type: Optional[str] = Field(
        default=None,
        description="Type of response: text, prompt, input, error"
    )
    options: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="Options for prompt responses (list of {key, value} dicts)"
    )
    options_text: Optional[str] = Field(
        default=None,
        description="Human-readable options string (e.g., 'Option A, Option B')"
    )
    preceding_messages: Optional[List[str]] = Field(
        default=None,
        description="Messages sent before the main response (e.g., welcome message before prompt)"
    )
    attachments: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="Response attachments"
    )
    status: str = Field(
        ...,
        description="Status: completed, pending, paused_for_input, paused_for_prompt, error"
    )
    workflow_status: Optional[str] = Field(
        default=None,
        description="Workflow execution status"
    )
    metadata: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Pass-through metadata from request"
    )
    created_at: datetime


class ApiMessageItem(BaseModel):
    """Single message in message list"""
    id: int
    message: str
    sender: str  # 'user' or 'agent'
    message_type: str
    attachments: Optional[List[Dict[str, Any]]] = None
    options: Optional[List[Dict[str, Any]]] = None
    timestamp: datetime


class ApiMessageList(BaseModel):
    """List of messages in a session"""
    session_id: str
    messages: List[ApiMessageItem]
    has_more: bool
    next_cursor: Optional[int] = Field(
        default=None,
        description="Message ID to use for next page"
    )


# ============ SESSION SCHEMAS ============

class ApiSessionCreate(BaseModel):
    """Create a new API session explicitly"""
    external_user_id: str = Field(..., description="Third-party's user identifier")
    name: Optional[str] = Field(default=None, description="Display name for the user")
    context: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Initial context variables"
    )
    metadata: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Additional metadata"
    )


class ApiSession(BaseModel):
    """API Session details"""
    session_id: str
    external_user_id: str
    status: str
    is_ai_enabled: bool
    workflow_id: Optional[int] = None
    agent_id: Optional[int] = None
    context: Dict[str, Any] = {}
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ApiSessionClose(BaseModel):
    """Close/resolve a session"""
    resolution_notes: Optional[str] = Field(
        default=None,
        description="Notes about how the conversation was resolved"
    )


class ApiSessionAiToggle(BaseModel):
    """Toggle AI for a session"""
    enabled: bool


# ============ WEBHOOK SCHEMAS ============

class WebhookPayload(BaseModel):
    """Payload sent to webhook URL for async responses"""
    event_type: str = Field(
        ...,
        description="Event type: message_response, session_update, error"
    )
    session_id: str
    external_user_id: str
    message_id: Optional[int] = None
    message: Optional[str] = None
    message_type: Optional[str] = None
    options: Optional[List[Dict[str, Any]]] = None
    attachments: Optional[List[Dict[str, Any]]] = None
    status: str
    timestamp: datetime
    metadata: Optional[Dict[str, Any]] = None
    signature: str = Field(..., description="HMAC-SHA256 signature for verification")


# ============ INTEGRATION SCHEMAS ============

class ApiIntegrationCreate(BaseModel):
    """Create API Integration"""
    name: str = Field(..., description="Name for this integration")
    description: Optional[str] = Field(default=None, description="Description")
    webhook_url: Optional[str] = Field(
        default=None,
        description="URL to POST async responses to"
    )
    webhook_secret: Optional[str] = Field(
        default=None,
        description="Secret for HMAC signature verification"
    )
    webhook_enabled: bool = Field(default=False)
    sync_response: bool = Field(
        default=True,
        description="Whether to wait for response in request by default"
    )
    default_agent_id: Optional[int] = Field(
        default=None,
        description="Default agent to use"
    )
    default_workflow_id: Optional[int] = Field(
        default=None,
        description="Default workflow to trigger"
    )
    rate_limit_requests: Optional[int] = Field(
        default=None,
        description="Max requests per rate limit window"
    )
    rate_limit_window: Optional[int] = Field(
        default=None,
        description="Rate limit window in seconds"
    )


class ApiIntegrationUpdate(BaseModel):
    """Update API Integration"""
    name: Optional[str] = None
    description: Optional[str] = None
    webhook_url: Optional[str] = None
    webhook_secret: Optional[str] = None
    webhook_enabled: Optional[bool] = None
    sync_response: Optional[bool] = None
    default_agent_id: Optional[int] = None
    default_workflow_id: Optional[int] = None
    rate_limit_requests: Optional[int] = None
    rate_limit_window: Optional[int] = None
    is_active: Optional[bool] = None


class ApiIntegrationResponse(BaseModel):
    """API Integration response"""
    id: int
    name: str
    description: Optional[str] = None
    api_key_id: int
    company_id: int
    webhook_url: Optional[str] = None
    webhook_enabled: bool
    sync_response: bool
    default_agent_id: Optional[int] = None
    default_workflow_id: Optional[int] = None
    rate_limit_requests: Optional[int] = None
    rate_limit_window: Optional[int] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    # Include API key info (without exposing the full key)
    api_key_name: Optional[str] = None
    api_key_prefix: Optional[str] = None  # First 8 chars for identification

    class Config:
        from_attributes = True


# ============ UTILITY SCHEMAS ============

class ApiStatusResponse(BaseModel):
    """Generic status response"""
    status: str
    message: Optional[str] = None


class ApiErrorResponse(BaseModel):
    """Error response"""
    error: str
    detail: Optional[str] = None
    code: Optional[str] = None
