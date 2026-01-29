"""
Pydantic schemas for Voice Workflow API.
"""
from pydantic import BaseModel, Field
from typing import Dict, Any, Optional, List
from datetime import datetime


class StartVoiceWorkflowRequest(BaseModel):
    """Request to start a voice workflow session."""
    workflow_json: Optional[Dict[str, Any]] = Field(None, description="The workflow JSON to execute (optional if agent_id provided)")
    agent_id: Optional[int] = Field(None, description="Agent ID to fetch active workflow from DB")
    company_id: Optional[int] = Field(None, description="Company ID for workflow lookup")
    user_name: Optional[str] = Field("Customer", description="Display name for the user")
    greeting_message: Optional[str] = Field(None, description="Custom greeting message")


class StartVoiceWorkflowResponse(BaseModel):
    """Response after starting a voice workflow session."""
    success: bool
    session_id: str
    room_name: str
    livekit_url: str
    user_token: str
    agent_token: str
    status: str = "starting"
    message: str = "Voice workflow session initiated"


class WorkflowStepRequest(BaseModel):
    """Request from agent to execute a workflow step."""
    session_id: str = Field(..., description="Unique session identifier")
    action: str = Field(..., description="Action to execute: 'create_incident', 'request_files', 'request_handoff'")
    data: str = Field("{}", description="JSON string of data collected from voice")


class WorkflowStepResponse(BaseModel):
    """Response to a workflow step request."""
    status: str = Field(..., description="Status: 'success', 'waiting_for_input', 'error'")
    message: Optional[str] = Field(None, description="Message for the agent")
    url: Optional[str] = Field(None, description="Form URL if waiting for input")
    data: Optional[Dict[str, Any]] = Field(None, description="Additional response data")


class FormField(BaseModel):
    """Definition of a form field."""
    name: str
    field_type: str  # text, file, select, textarea, location
    label: str
    required: bool = True
    options: Optional[List[str]] = None  # For select fields
    placeholder: Optional[str] = None


class PendingFormData(BaseModel):
    """Data for a pending form session."""
    session_id: str
    room_name: str
    workflow_json: Dict[str, Any]
    voice_captured_data: Dict[str, Any] = {}
    required_fields: List[FormField] = []
    created_at: datetime = Field(default_factory=datetime.utcnow)
    status: str = "pending"  # pending, submitted, completed


class FormSubmissionRequest(BaseModel):
    """Form submission data."""
    fields: Dict[str, Any] = Field({}, description="Form field values")


class HandoffRequest(BaseModel):
    """Request to hand off to a human agent."""
    session_id: str
    reason: str = Field(..., description="Reason for handoff")
    team_name: str = Field("Support", description="Team to assign to")
    priority: str = Field("normal", description="Priority: 'normal' or 'urgent'")
    transcript: Optional[str] = Field(None, description="Conversation transcript so far")


class HandoffResponse(BaseModel):
    """Response to handoff request."""
    status: str
    message: str
    agent_id: Optional[int] = None
    agent_name: Optional[str] = None
