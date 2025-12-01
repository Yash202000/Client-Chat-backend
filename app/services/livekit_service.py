"""
LiveKit service for managing voice/video calls.
"""
from livekit import api
from app.core.config import settings
from typing import Dict
import time


def generate_livekit_token(room_name: str, identity: str, participant_name: str = None) -> str:
    """
    Generate a LiveKit access token for a participant.

    Args:
        room_name: Name of the LiveKit room
        identity: Unique identifier for the participant
        participant_name: Display name for the participant (optional)

    Returns:
        JWT token string
    """
    if not all([settings.LIVEKIT_API_KEY, settings.LIVEKIT_API_SECRET]):
        raise ValueError("LiveKit API credentials not configured")

    token = api.AccessToken(
        settings.LIVEKIT_API_KEY,
        settings.LIVEKIT_API_SECRET
    )

    token.with_identity(identity)

    if participant_name:
        token.with_name(participant_name)

    token.with_grants(
        api.VideoGrants(
            room_join=True,
            room=room_name,
            can_publish=True,
            can_subscribe=True,
            can_publish_data=True
        )
    )

    return token.to_jwt()


def create_call_room(session_id: str, user_identity: str, agent_identity: str,
                     user_name: str = "Customer", agent_name: str = "Agent") -> Dict:
    """
    Create a LiveKit room for a handoff call.

    Args:
        session_id: Conversation session ID
        user_identity: Unique identifier for the user
        agent_identity: Unique identifier for the agent
        user_name: Display name for the user
        agent_name: Display name for the agent

    Returns:
        Dictionary with room details and tokens
    """
    # Generate unique room name
    timestamp = int(time.time())
    room_name = f"handoff_{session_id}_{timestamp}"

    # Generate tokens for both participants
    user_token = generate_livekit_token(room_name, user_identity, user_name)
    agent_token = generate_livekit_token(room_name, agent_identity, agent_name)

    return {
        "room_name": room_name,
        "livekit_url": settings.LIVEKIT_URL,
        "user_token": user_token,
        "agent_token": agent_token
    }
