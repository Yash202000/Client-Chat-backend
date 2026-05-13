from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
from livekit import api
from app.core.config import settings
from sqlalchemy.orm import Session
from app.core.dependencies import get_db, get_current_user
from app.models.user import User
from app.crud import crud_video_call, crud_chat, crud_notification
from app.schemas.video_call import VideoCallCreate
from app.schemas import chat as chat_schema
from app.schemas.websockets import WebSocketMessage
from app.services.connection_manager import manager
import json
import logging
logger = logging.getLogger(__name__)


async def _broadcast_system_message(db_message, channel_id: int):
    """Broadcast a system message as a new_message WebSocket event."""
    if db_message is None:
        return
    try:
        message_data = chat_schema.InternalChatMessage.from_orm(db_message)
        ws_msg = WebSocketMessage(type="new_message", payload=message_data.model_dump())
        await manager.broadcast(ws_msg.model_dump_json(), str(channel_id))
    except Exception:
        logger.exception("Unexpected error")

router = APIRouter()

class TokenRequest(BaseModel):
    room_name: str
    participant_name: str

class PublicTokenRequest(BaseModel):
    room_name: str
    participant_name: str
    agent_id: Optional[int] = None

def get_livekit_token(room_name: str, participant_name: str):
    if not settings.LIVEKIT_API_KEY or not settings.LIVEKIT_API_SECRET or not settings.LIVEKIT_URL:
        raise HTTPException(status_code=500, detail="LiveKit server not configured. Please check your .env file.")

    video_grant = api.VideoGrants(room=room_name, room_join=True, can_publish=True, can_subscribe=True)

    user_token = api.AccessToken(settings.LIVEKIT_API_KEY, settings.LIVEKIT_API_SECRET).with_identity(participant_name).with_name(participant_name).with_grants(video_grant)

    return user_token.to_jwt()

@router.post("/token")
def get_public_token(request: PublicTokenRequest):
    """Generate LiveKit token for voice mode widget (public endpoint)"""
    token = get_livekit_token(request.room_name, request.participant_name)
    return {
        "access_token": token,
        "livekit_url": settings.LIVEKIT_URL
    }

@router.post("/channels/{channel_id}/initiate")
async def initiate_video_call(
    channel_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    channel = crud_chat.get_channel(db, channel_id=channel_id)
    channel_type_str = str(channel.channel_type.value if hasattr(channel.channel_type, 'value') else channel.channel_type).upper()

    channel_members = crud_chat.get_channel_members(db, channel_id=channel_id)
    channel_member_ids = [member.id for member in channel_members]

    # Only ring for true 1-on-1 DMs (type=DM AND exactly 2 members)
    is_dm = channel_type_str == 'DM' and len(channel_member_ids) == 2

    # DM calls ring the other person; team/group calls go straight to active (silent join room)
    initial_status = "ringing" if is_dm else "active"
    video_call = crud_video_call.create_video_call(db, obj_in=VideoCallCreate(channel_id=channel_id), created_by_id=current_user.id)
    crud_video_call.update_video_call_status(db, video_call_id=video_call.id, status=initial_status)

    video_call = crud_video_call.add_user_to_joined_users(db, video_call_id=video_call.id, user_id=current_user.id)

    token = get_livekit_token(video_call.room_name, current_user.email)

    call_data = json.dumps({
        "type": "video_call_initiated",
        "call_id": video_call.id,
        "room_name": video_call.room_name,
        "livekit_token": token,
        "livekit_url": settings.LIVEKIT_URL,
        "channel_id": channel_id,
        "channel_type": channel_type_str if channel else "DM",
        "channel_member_ids": channel_member_ids,
        "caller_id": current_user.id,
        "caller_name": current_user.first_name or current_user.email,
        "caller_avatar": current_user.profile_picture_url,
    })

    # Broadcast to channel WebSocket (active call button for members on chat page)
    await manager.broadcast(call_data, str(channel_id))

    # Broadcast company-wide so users on other pages get notified too
    await manager.broadcast(call_data, str(current_user.company_id))

    return {
        "call_id": video_call.id,
        "room_name": video_call.room_name,
        "livekit_token": token,
        "livekit_url": settings.LIVEKIT_URL
    }

@router.post("/channels/{channel_id}/join")
def join_video_call(
    channel_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    video_call = crud_video_call.get_active_video_call_by_channel(db, channel_id=channel_id)
    if not video_call:
        raise HTTPException(status_code=404, detail="No active video call found for this channel.")
    
    crud_video_call.add_participant_to_video_call(db, video_call_id=video_call.id, user_id=current_user.id)
    token = get_livekit_token(video_call.room_name, current_user.email)
    return {
        "call_id": video_call.id,
        "room_name": video_call.room_name,
        "livekit_token": token,
        "livekit_url": settings.LIVEKIT_URL
    }

@router.get("/channels/{channel_id}/active")
def get_active_video_call(
    channel_id: int,
    db: Session = Depends(get_db),
):
    # First check for a direct channel video call
    video_call = crud_video_call.get_active_video_call_by_channel(db, channel_id=channel_id)
    if video_call:
        return {"room_name": video_call.room_name, "livekit_url": settings.LIVEKIT_URL, "source": "channel"}

    # Fall back to a calendar meeting linked to this channel.
    # Only requirement: a room has been started (livekit_room_name is set).
    # No time constraints — users can join at any time.
    from app.models.calendar_event import CalendarEvent
    cal_event = (
        db.query(CalendarEvent)
        .filter(
            CalendarEvent.channel_id == channel_id,
            CalendarEvent.livekit_room_name.isnot(None),
        )
        .order_by(CalendarEvent.start_time.desc())
        .first()
    )
    if cal_event:
        return {
            "room_name": cal_event.livekit_room_name,
            "livekit_url": settings.LIVEKIT_URL,
            "source": "calendar",
            "event_id": cal_event.id,
        }

    raise HTTPException(status_code=404, detail="No active video call found for this channel.")

@router.post("/{call_id}/reject")
async def reject_video_call(
    call_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Reject an incoming video call"""
    video_call = crud_video_call.get_video_call_by_id(db, call_id=call_id)
    if not video_call:
        raise HTTPException(status_code=404, detail="Video call not found")

    if video_call.status != "ringing":
        raise HTTPException(status_code=400, detail="Call is not in ringing state")

    # Update call status to rejected
    video_call = crud_video_call.reject_video_call(db, video_call_id=call_id, rejected_by_id=current_user.id)

    user_name = current_user.first_name or current_user.email
    is_caller_cancelling = video_call.created_by_id == current_user.id

    # System message differs: caller cancelled vs callee declined
    system_message_content = "📵 Call cancelled" if is_caller_cancelling else f"📵 Call declined by {user_name}"
    sys_msg = crud_chat.create_system_message(
        db=db,
        channel_id=video_call.channel_id,
        content=system_message_content,
        extra_data={"call_id": call_id, "call_status": "rejected"}
    )
    await _broadcast_system_message(sys_msg, video_call.channel_id)

    # Notify the caller if callee declined
    if not is_caller_cancelling:
        crud_notification.create_notification(
            db=db,
            user_id=video_call.created_by_id,
            notification_type="call_rejected",
            title=f"{user_name} declined your call",
            message=f"Your video call was declined by {user_name}",
            related_channel_id=video_call.channel_id,
            actor_id=current_user.id
        )

    reject_payload = json.dumps({
        "type": "call_rejected",
        "call_id": call_id,
        "room_name": video_call.room_name,
        "channel_id": video_call.channel_id,
        "rejected_by_id": current_user.id,
        "rejected_by_name": user_name,
        "cancelled_by_caller": is_caller_cancelling,
    })

    # Broadcast to channel WS (for InternalChatPage) and company WS (for AppLayout ring modal)
    await manager.broadcast(reject_payload, str(video_call.channel_id))
    await manager.broadcast(reject_payload, str(current_user.company_id))

    return {"status": "rejected", "message": "Call rejected successfully"}

@router.post("/{call_id}/accept")
async def accept_video_call(
    call_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Accept/Join an incoming video call"""

    video_call = crud_video_call.get_video_call_by_id(db, call_id=call_id)
    if not video_call:
        raise HTTPException(status_code=404, detail="Video call not found")


    # Allow accepting/joining calls that are "ringing" or "active" (for group calls)
    if video_call.status not in ["ringing", "active"]:
        raise HTTPException(status_code=400, detail=f"Call is not available to join (status: {video_call.status})")

    # Check if this is the first person accepting (transitioning from ringing to active)
    is_first_accept = video_call.status == "ringing"


    # Update call status to active and add user to participants
    video_call = crud_video_call.accept_video_call(db, video_call_id=call_id, accepted_by_id=current_user.id)

    acceptor_name = current_user.first_name or current_user.email

    # Only create system message for the first accept (when call starts)
    if is_first_accept:
        system_message_content = f"📞 Video call started by {acceptor_name}"
        sys_msg = crud_chat.create_system_message(
            db=db,
            channel_id=video_call.channel_id,
            content=system_message_content,
            extra_data={"call_id": call_id, "call_status": "active"}
        )
        await _broadcast_system_message(sys_msg, video_call.channel_id)
    # Generate token for the accepter
    token = get_livekit_token(video_call.room_name, current_user.email)

    # Broadcast acceptance/join to all channel members
    broadcast_type = "call_accepted" if is_first_accept else "user_joined_call"

    accept_payload = json.dumps({
        "type": broadcast_type,
        "call_id": call_id,
        "room_name": video_call.room_name,
        "livekit_url": settings.LIVEKIT_URL,
        "channel_id": video_call.channel_id,
        "caller_id": video_call.created_by_id,
        "accepted_by_id": current_user.id,
        "accepted_by_name": acceptor_name,
        "participant_count": len(video_call.joined_users) if video_call.joined_users else 1,
    })
    await manager.broadcast(accept_payload, str(video_call.channel_id))
    # Also notify company-wide so AppLayout can dismiss the ring modal on all devices
    await manager.broadcast(accept_payload, str(current_user.company_id))


    return {
        "status": "accepted",
        "room_name": video_call.room_name,
        "livekit_token": token,
        "livekit_url": settings.LIVEKIT_URL
    }

@router.post("/{call_id}/end")
async def end_video_call(
    call_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Leave or end a video call"""

    video_call = crud_video_call.get_video_call_by_id(db, call_id=call_id)
    if not video_call:
        raise HTTPException(status_code=404, detail="Video call not found")

    # Already ended — return early so concurrent /end requests don't duplicate messages
    if video_call.status == "completed":
        return {"status": "completed"}


    # Get current participants in the call
    joined_users = video_call.joined_users if video_call.joined_users else []

    # Calculate how many users will remain after this user leaves
    remaining_users = [uid for uid in joined_users if uid != current_user.id]
    remaining_count = len(remaining_users)

    user_name = current_user.first_name or current_user.email

    # Keep call alive as long as at least 1 other user remains; end only when last person leaves
    if remaining_count >= 1:

        # Remove this user from joined_users
        video_call = crud_video_call.remove_participant_from_video_call(db, video_call_id=call_id, user_id=current_user.id)

        # Broadcast user left to all channel members
        broadcast_data = {
            "type": "user_left_call",
            "call_id": call_id,
            "room_name": video_call.room_name,
            "channel_id": video_call.channel_id,
            "left_by_id": current_user.id,
            "left_by_name": user_name,
            "participant_count": remaining_count,
        }

        await manager.broadcast(
            json.dumps(broadcast_data),
            str(video_call.channel_id)
        )

        return {"status": "left", "participant_count": remaining_count}

    # This is the last user - end the call completely

    # Update call status to completed
    video_call = crud_video_call.end_video_call(db, video_call_id=call_id)

    # Calculate duration if answered_at exists
    duration_seconds = None
    if video_call.answered_at and video_call.ended_at:
        duration_seconds = int((video_call.ended_at - video_call.answered_at).total_seconds())


    # Create system message in chat
    if duration_seconds:
        minutes = duration_seconds // 60
        seconds = duration_seconds % 60
        duration_str = f"{minutes}:{seconds:02d}" if minutes > 0 else f"{seconds}s"
        system_message_content = f"📞 Video call ended · Duration: {duration_str}"
    else:
        system_message_content = "📞 Video call ended"

    sys_msg = crud_chat.create_system_message(
        db=db,
        channel_id=video_call.channel_id,
        content=system_message_content,
        extra_data={"call_id": call_id, "call_status": "completed", "duration_seconds": duration_seconds}
    )
    await _broadcast_system_message(sys_msg, video_call.channel_id)

    # Broadcast call end to all channel members
    broadcast_data = {
        "type": "call_ended",
        "call_id": call_id,
        "room_name": video_call.room_name,
        "channel_id": video_call.channel_id,
        "ended_by_id": current_user.id,
        "duration_seconds": duration_seconds,
    }

    end_payload = json.dumps(broadcast_data)
    await manager.broadcast(end_payload, str(video_call.channel_id))
    # Also notify company-wide so AppLayout can dismiss any stale ring modals
    await manager.broadcast(end_payload, str(current_user.company_id))

    return {"status": "completed", "duration_seconds": duration_seconds}

@router.get("/channels/{channel_id}/history")
def get_call_history(
    channel_id: int,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get call history for a channel"""
    calls = crud_video_call.get_call_history(db, channel_id=channel_id, limit=limit)

    # Format response with call details
    history = []
    for call in calls:
        duration_seconds = None
        if call.answered_at and call.ended_at:
            duration_seconds = int((call.ended_at - call.answered_at).total_seconds())

        history.append({
            "id": call.id,
            "room_name": call.room_name,
            "status": call.status,
            "created_by_id": call.created_by_id,
            "started_at": call.started_at.isoformat() if call.started_at else None,
            "answered_at": call.answered_at.isoformat() if call.answered_at else None,
            "ended_at": call.ended_at.isoformat() if call.ended_at else None,
            "duration_seconds": duration_seconds,
            "participants": call.participants,
            "joined_users": call.joined_users,
        })

    return history
