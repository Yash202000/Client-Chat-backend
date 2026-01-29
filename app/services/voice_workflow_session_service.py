"""
Voice Workflow Session Service - In-memory session management for voice workflow forms.

This service manages pending form sessions, storing voice-captured data 
while waiting for additional form input from users.
"""
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from threading import Lock
import json

from app.schemas.voice_workflow import PendingFormData, FormField

logger = logging.getLogger(__name__)

# In-memory storage for pending forms
# In production, consider using Redis for persistence across instances
_pending_forms: Dict[str, PendingFormData] = {}
_lock = Lock()

# Session timeout in seconds (default: 30 minutes)
SESSION_TIMEOUT_SECONDS = 1800


def create_session(
    session_id: str,
    room_name: str,
    workflow_json: Dict[str, Any],
    voice_captured_data: Optional[Dict[str, Any]] = None,
    required_fields: Optional[List[FormField]] = None
) -> PendingFormData:
    """
    Create a new pending form session.
    
    Args:
        session_id: Unique session identifier
        room_name: LiveKit room name
        workflow_json: The workflow being executed
        voice_captured_data: Data already captured via voice
        required_fields: List of form fields required
        
    Returns:
        PendingFormData object
    """
    with _lock:
        session = PendingFormData(
            session_id=session_id,
            room_name=room_name,
            workflow_json=workflow_json,
            voice_captured_data=voice_captured_data or {},
            required_fields=required_fields or [],
            created_at=datetime.utcnow(),
            status="pending"
        )
        _pending_forms[session_id] = session
        logger.info(f"Created voice workflow session: {session_id}")
        return session


def get_session(session_id: str) -> Optional[PendingFormData]:
    """
    Get a pending form session by ID.
    
    Args:
        session_id: Session identifier
        
    Returns:
        PendingFormData if found, None otherwise
    """
    with _lock:
        session = _pending_forms.get(session_id)
        if session:
            # Check for timeout
            if datetime.utcnow() - session.created_at > timedelta(seconds=SESSION_TIMEOUT_SECONDS):
                logger.warning(f"Session {session_id} has timed out")
                del _pending_forms[session_id]
                return None
        return session


def update_session(
    session_id: str,
    voice_data: Optional[Dict[str, Any]] = None,
    form_data: Optional[Dict[str, Any]] = None,
    status: Optional[str] = None
) -> Optional[PendingFormData]:
    """
    Update an existing session with new data.
    
    Args:
        session_id: Session identifier
        voice_data: Additional voice-captured data to merge
        form_data: Form submission data to merge
        status: New status
        
    Returns:
        Updated PendingFormData if found
    """
    with _lock:
        session = _pending_forms.get(session_id)
        if not session:
            logger.warning(f"Session {session_id} not found for update")
            return None
        
        if voice_data:
            session.voice_captured_data.update(voice_data)
        
        if form_data:
            session.voice_captured_data.update(form_data)
        
        if status:
            session.status = status
        
        _pending_forms[session_id] = session
        logger.info(f"Updated session {session_id}: status={session.status}")
        return session


def complete_session(session_id: str) -> Optional[Dict[str, Any]]:
    """
    Complete a session and return all collected data.
    
    Args:
        session_id: Session identifier
        
    Returns:
        Combined voice and form data
    """
    with _lock:
        session = _pending_forms.get(session_id)
        if not session:
            return None
        
        session.status = "completed"
        all_data = session.voice_captured_data.copy()
        
        logger.info(f"Completed session {session_id}")
        return all_data


def delete_session(session_id: str) -> bool:
    """
    Delete a session.
    
    Args:
        session_id: Session identifier
        
    Returns:
        True if deleted, False if not found
    """
    with _lock:
        if session_id in _pending_forms:
            del _pending_forms[session_id]
            logger.info(f"Deleted session {session_id}")
            return True
        return False


def cleanup_expired_sessions() -> int:
    """
    Clean up expired sessions.
    
    Returns:
        Number of sessions cleaned up
    """
    with _lock:
        now = datetime.utcnow()
        expired = [
            sid for sid, session in _pending_forms.items()
            if now - session.created_at > timedelta(seconds=SESSION_TIMEOUT_SECONDS)
        ]
        for sid in expired:
            del _pending_forms[sid]
        
        if expired:
            logger.info(f"Cleaned up {len(expired)} expired sessions")
        return len(expired)


def get_all_sessions() -> Dict[str, PendingFormData]:
    """
    Get all active sessions (for debugging/monitoring).
    
    Returns:
        Dictionary of all pending sessions
    """
    with _lock:
        return _pending_forms.copy()


def determine_required_fields(workflow_json: Dict[str, Any], voice_data: Dict[str, Any]) -> List[FormField]:
    """
    Analyze workflow to determine what fields are still needed.
    
    Args:
        workflow_json: The workflow definition
        voice_data: Data already captured via voice
        
    Returns:
        List of FormField objects for the form
    """
    required_fields = []
    
    # Look for nodes in the workflow that require specific inputs
    nodes = workflow_json.get("nodes", []) or workflow_json.get("visual_steps", {}).get("nodes", [])
    
    for node in nodes:
        node_data = node.get("data", {})
        node_type = node.get("type", "")
        
        # Check for file upload requirements
        if node_type == "file_upload" or node_data.get("requires_file"):
            if "file" not in voice_data and "image" not in voice_data:
                required_fields.append(FormField(
                    name="file_upload",
                    field_type="file",
                    label="Upload File or Image",
                    required=True
                ))
        
        # Check for location requirements
        if node_type == "location" or node_data.get("requires_location"):
            if "location" not in voice_data and "gps" not in voice_data:
                required_fields.append(FormField(
                    name="location",
                    field_type="location",
                    label="Your Location",
                    required=True
                ))
        
        # Check for signature requirements
        if node_data.get("requires_signature"):
            required_fields.append(FormField(
                name="signature",
                field_type="file",
                label="Your Signature",
                required=True
            ))
    
    # Always add a general notes field if we're requesting files
    if required_fields:
        required_fields.append(FormField(
            name="additional_notes",
            field_type="textarea",
            label="Additional Notes (optional)",
            required=False,
            placeholder="Any additional information..."
        ))
    
    return required_fields
