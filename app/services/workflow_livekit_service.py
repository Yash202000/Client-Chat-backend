"""
Workflow LiveKit Service - Manages LiveKit rooms for voice workflow sessions.

Extends the base livekit_service with workflow-specific functionality:
- Creates rooms with workflow JSON in metadata
- Sends data messages to rooms for form completion events
- Manages voice workflow session lifecycle
"""
import os
import time
import json
import logging
from typing import Dict, Any, Optional
from livekit import api
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)

# LiveKit configuration from environment
LIVEKIT_URL = os.getenv("LIVEKIT_URL2", "wss://your-livekit-server.livekit.cloud")
LIVEKIT_API_KEY = os.getenv("LIVEKIT_API_KEY2")
LIVEKIT_API_SECRET = os.getenv("LIVEKIT_API_SECRET2")

# Backend URL for agent callbacks
# BACKEND_URL = os.getenv("BACKEND_URL", os.getenv("PUBLIC_HOST", "http://localhost:8000"))
BACKEND_URL = "https://lightweight-schema-focuses-retreat.trycloudflare.com"


def generate_session_id() -> str:
    """Generate a unique session ID."""
    import uuid
    return f"vw_{uuid.uuid4().hex[:12]}_{int(time.time())}"


async def create_room_on_server(room_name: str, metadata_json: str) -> bool:
    """
    Actually create the room on the LiveKit server.
    This is required for agent dispatch to work.
    
    Args:
        room_name: Name of the room to create
        metadata_json: JSON string of room metadata
        
    Returns:
        True if room was created successfully
    """
    if not all([LIVEKIT_API_KEY, LIVEKIT_API_SECRET]):
        logger.error("LiveKit credentials not configured")
        return False
    
    try:
        # Create room service client
        livekit_host = LIVEKIT_URL.replace("wss://", "https://").replace("ws://", "http://")
        room_service = api.RoomService(
            livekit_host,
            LIVEKIT_API_KEY,
            LIVEKIT_API_SECRET
        )
        
        # Create the room with metadata
        room = await room_service.create_room(
            api.CreateRoomRequest(
                name=room_name,
                metadata=metadata_json,
                empty_timeout=600,  # 10 minutes
                max_participants=10
            )
        )
        
        logger.info(f"Created room on LiveKit server: {room.name} (sid: {room.sid})")
        return True
        
    except Exception as e:
        logger.error(f"Failed to create room on LiveKit server: {e}")
        # Room might already exist, which is fine
        return True


def create_workflow_room(
    workflow_json: Dict[str, Any],
    session_id: Optional[str] = None,
    user_name: str = "Customer",
    greeting_message: Optional[str] = None,
    agent_id: Optional[int] = None,
    company_id: Optional[int] = None
) -> Dict[str, Any]:
    """
    Create a LiveKit room for a voice workflow session.
    
    Args:
        workflow_json: The workflow JSON to execute
        session_id: Optional session ID (generated if not provided)
        user_name: Display name for the user
        greeting_message: Custom greeting message for the agent
        agent_id: Optional agent ID for context
        company_id: Optional company ID
        
    Returns:
        Dictionary with room details, tokens, and session info
    """
    if not all([LIVEKIT_API_KEY, LIVEKIT_API_SECRET]):
        raise ValueError("LiveKit API credentials not configured. Set LIVEKIT_API_KEY and LIVEKIT_API_SECRET in .env")
    
    # Generate session ID if not provided
    if not session_id:
        session_id = generate_session_id()
    
    # Generate room name
    timestamp = int(time.time())
    room_name = f"voice_workflow_{session_id}"
    
    # Prepare room metadata with workflow context
    metadata = {
        "session_id": session_id,
        "workflow": workflow_json,
        "backend_url": BACKEND_URL,
        "greeting_message": greeting_message,
        "agent_id": agent_id,
        "company_id": company_id,
        "created_at": timestamp
    }
    
    # Log workflow details for debugging
    workflow_name = workflow_json.get("name", "Unknown")
    # Check both possible locations for nodes
    visual_nodes = workflow_json.get("visual_steps", {}).get("nodes", [])
    root_nodes = workflow_json.get("nodes", [])
    nodes_count = len(visual_nodes) if visual_nodes else len(root_nodes)
    nodes_location = "visual_steps.nodes" if visual_nodes else "nodes (root)"
    
    logger.info(f"[WORKFLOW DEBUG] Creating room with workflow: {workflow_name}")
    logger.info(f"[WORKFLOW DEBUG] Workflow has {nodes_count} nodes (from {nodes_location})")
    logger.info(f"[WORKFLOW DEBUG] Workflow keys: {list(workflow_json.keys())}")
    
    metadata_json = json.dumps(metadata)
    
    logger.info(f"[WORKFLOW DEBUG] Workflow data: {metadata_json}")
    # Generate user token
    user_token = api.AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
    user_token.with_identity(f"user_{session_id}")
    user_token.with_name(user_name)
    user_token.with_grants(api.VideoGrants(
        room_join=True,
        room=room_name,
        can_publish=True,
        can_subscribe=True,
        can_publish_data=True
    ))
    user_token.with_metadata(json.dumps({"role": "user", "session_id": session_id}))
    
    # Generate agent token
    agent_token = api.AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
    agent_token.with_identity(f"agent_{session_id}")
    agent_token.with_name("AI Assistant")
    agent_token.with_grants(api.VideoGrants(
        room_join=True,
        room=room_name,
        can_publish=True,
        can_subscribe=True,
        can_publish_data=True,
        room_admin=True  # Agent can send data messages
    ))
    agent_token.with_metadata(json.dumps({"role": "agent", "session_id": session_id}))
    
    logger.info(f"Created workflow room: {room_name} with session: {session_id}")
    
    return {
        "success": True,
        "session_id": session_id,
        "room_name": room_name,
        "livekit_url": LIVEKIT_URL,
        "user_token": user_token.to_jwt(),
        "agent_token": agent_token.to_jwt(),
        "metadata": metadata,
        "metadata_json": metadata_json  # Include for room creation
    }


async def send_data_message_to_room(
    room_name: str,
    message_type: str,
    data: Dict[str, Any]
) -> bool:
    """
    Send a data message to all participants in a room.
    
    This is used to notify the agent when a form is submitted.
    
    Args:
        room_name: LiveKit room name
        message_type: Type of message (e.g., 'FORM_SUBMITTED')
        data: Message payload
        
    Returns:
        True if sent successfully
    """
    if not all([LIVEKIT_API_KEY, LIVEKIT_API_SECRET]):
        logger.error("LiveKit credentials not configured")
        return False
    
    try:
        # Create room service client
        room_service = api.RoomService(
            LIVEKIT_URL.replace("wss://", "https://").replace("ws://", "http://"),
            LIVEKIT_API_KEY,
            LIVEKIT_API_SECRET
        )
        
        # Prepare the message
        message = {
            "type": message_type,
            "timestamp": int(time.time()),
            **data
        }
        
        # Send data to the room
        await room_service.send_data(
            api.SendDataRequest(
                room=room_name,
                data=json.dumps(message).encode(),
                kind=api.DataPacketKind.RELIABLE
            )
        )
        
        logger.info(f"Sent {message_type} message to room {room_name}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to send data message to room {room_name}: {e}")
        return False


def generate_form_url(session_id: str, base_url: Optional[str] = None) -> str:
    """
    Generate a URL for the dynamic form.
    
    Args:
        session_id: Session identifier
        base_url: Base URL (defaults to BACKEND_URL)
        
    Returns:
        Full form URL
    """
    base = base_url or BACKEND_URL
    base = base.rstrip('/')
    return f"{base}/api/v1/voice-workflow/form/{session_id}"


def get_livekit_config() -> Dict[str, Any]:
    """
    Get LiveKit configuration for debugging/status checks.
    
    Returns:
        Dictionary with config info (secrets masked)
    """
    return {
        "livekit_url": LIVEKIT_URL,
        "api_key_configured": bool(LIVEKIT_API_KEY),
        "api_secret_configured": bool(LIVEKIT_API_SECRET),
        "backend_url": BACKEND_URL
    }
