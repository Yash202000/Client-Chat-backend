
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from sqlalchemy.orm import Session
import uuid
import base64
import datetime
import json

from app.core.dependencies import get_db
from app.models.user import User
from app.core.auth import get_current_user
from app.services.connection_manager import manager

router = APIRouter()

# File upload configuration
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
ALLOWED_FILE_TYPES = {
    "image/png", "image/jpeg", "image/jpg", "image/gif", "image/webp",
    "application/pdf", "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "text/plain", "text/csv",
    "application/zip", "application/x-rar-compressed"
}


@router.post("/conversation/upload")
async def upload_conversation_file(
    file: UploadFile = File(...),
    session_id: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Upload a file for a public conversation and broadcast it directly to the widget client
    WITHOUT saving to S3 - file is sent in real-time via WebSocket only

    This is specifically for agent-to-customer conversations in the widget.
    Internal team chat uses the regular /upload endpoint which saves to S3.
    """

    # Validate file type
    if file.content_type not in ALLOWED_FILE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File type {file.content_type} is not allowed"
        )

    # Read file content
    content = await file.read()
    file_size = len(content)

    # Validate file size
    if file_size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File size ({file_size} bytes) exceeds maximum allowed size ({MAX_FILE_SIZE} bytes)"
        )

    # Convert file content to base64 for transmission
    file_base64 = base64.b64encode(content).decode('utf-8')

    # Create attachment data to broadcast
    attachment_data = {
        "file_name": file.filename,
        "file_type": file.content_type,
        "file_size": file_size,
        "file_data": file_base64  # Base64 encoded file content for real-time transmission
    }

    # Create message to broadcast via WebSocket
    message_payload = {
        "id": f"attachment_{uuid.uuid4()}",
        "sender": "agent",
        "message": f"📎 {file.filename}",
        "message_type": "message",
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "assignee_name": f"{current_user.first_name} {current_user.last_name}".strip() or current_user.email,
        "attachments": [attachment_data]
    }

    # Broadcast to session via WebSocket
    try:
        await manager.broadcast_to_session(
            session_id,
            json.dumps(message_payload),
            "agent"
        )

        return {
            "success": True,
            "message": "File broadcasted to widget client",
            "file_name": file.filename,
            "file_size": file_size,
            "session_id": session_id
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to broadcast file: {str(e)}"
        )
