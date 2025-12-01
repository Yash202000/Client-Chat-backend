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
from app.services.connection_manager import manager
import json

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
    video_call = crud_video_call.create_video_call(db, obj_in=VideoCallCreate(channel_id=channel_id), created_by_id=current_user.id)
    crud_video_call.update_video_call_status(db, video_call_id=video_call.id, status="ringing")

    # Add caller to joined_users since they're joining immediately (but keep status as "ringing")
    video_call = crud_video_call.add_user_to_joined_users(db, video_call_id=video_call.id, user_id=current_user.id)
    print(f"[INITIATE CALL] Caller {current_user.id} added to joined_users: {video_call.joined_users}")

    # Get channel members to filter notifications on frontend
    channel_members = crud_chat.get_channel_members(db, channel_id=channel_id)
    channel_member_ids = [member.id for member in channel_members]
    print(f"[INITIATE CALL] Channel {channel_id} has members: {channel_member_ids}")

    token = get_livekit_token(video_call.room_name, current_user.email)

    call_data = json.dumps({
        "type": "video_call_initiated",
        "call_id": video_call.id,
        "room_name": video_call.room_name,
        "livekit_token": token,
        "livekit_url": settings.LIVEKIT_URL,
        "channel_id": channel_id,
        "channel_member_ids": channel_member_ids,
        "caller_id": current_user.id,
        "caller_name": current_user.first_name or current_user.email,
        "caller_avatar": current_user.profile_picture_url,
    })

    # Broadcast to channel-specific WebSocket (for users on that channel)
    await manager.broadcast(call_data, str(channel_id))

    # Also broadcast to company-level WebSocket (for ALL users in company, even if not on channel)
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
    video_call = crud_video_call.get_active_video_call_by_channel(db, channel_id=channel_id)
    if not video_call:
        raise HTTPException(status_code=404, detail="No active video call found for this channel.")
    return {"room_name": video_call.room_name, "livekit_url": settings.LIVEKIT_URL}

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

    # Create system message in chat
    rejector_name = current_user.first_name or current_user.email
    system_message_content = f"📵 Call declined by {rejector_name}"
    crud_chat.create_system_message(
        db=db,
        channel_id=video_call.channel_id,
        content=system_message_content,
        extra_data={"call_id": call_id, "call_status": "rejected"}
    )

    # Create notification for the caller
    if video_call.created_by_id != current_user.id:
        crud_notification.create_notification(
            db=db,
            user_id=video_call.created_by_id,
            notification_type="call_rejected",
            title=f"{rejector_name} declined your call",
            message=f"Your video call was declined by {rejector_name}",
            related_channel_id=video_call.channel_id,
            actor_id=current_user.id
        )

    # Broadcast rejection to all channel members
    await manager.broadcast(
        json.dumps({
            "type": "call_rejected",
            "call_id": call_id,
            "room_name": video_call.room_name,
            "channel_id": video_call.channel_id,
            "rejected_by_id": current_user.id,
            "rejected_by_name": current_user.first_name or current_user.email,
        }),
        str(video_call.channel_id)
    )

    return {"status": "rejected", "message": "Call rejected successfully"}

@router.post("/{call_id}/accept")
async def accept_video_call(
    call_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Accept/Join an incoming video call"""
    print(f"[ACCEPT CALL] User {current_user.id} ({current_user.email}) attempting to accept call {call_id}")

    video_call = crud_video_call.get_video_call_by_id(db, call_id=call_id)
    if not video_call:
        print(f"[ACCEPT CALL] ERROR: Call {call_id} not found")
        raise HTTPException(status_code=404, detail="Video call not found")

    print(f"[ACCEPT CALL] Call status: {video_call.status}")

    # Allow accepting/joining calls that are "ringing" or "active" (for group calls)
    if video_call.status not in ["ringing", "active"]:
        print(f"[ACCEPT CALL] ERROR: Call status is {video_call.status}, not ringing/active")
        raise HTTPException(status_code=400, detail=f"Call is not available to join (status: {video_call.status})")

    # Check if this is the first person accepting (transitioning from ringing to active)
    is_first_accept = video_call.status == "ringing"

    print(f"[ACCEPT CALL] is_first_accept: {is_first_accept}")

    # Update call status to active and add user to participants
    video_call = crud_video_call.accept_video_call(db, video_call_id=call_id, accepted_by_id=current_user.id)
    print(f"[ACCEPT CALL] User {current_user.id} added to joined_users: {video_call.joined_users}")

    acceptor_name = current_user.first_name or current_user.email

    # Only create system message for the first accept (when call starts)
    if is_first_accept:
        print(f"[ACCEPT CALL] Creating system message for first accept")
        system_message_content = f"📞 Video call started by {acceptor_name}"
        crud_chat.create_system_message(
            db=db,
            channel_id=video_call.channel_id,
            content=system_message_content,
            extra_data={"call_id": call_id, "call_status": "active"}
        )
    else:
        print(f"[ACCEPT CALL] User joining existing call, creating join message")
        # Create a system message for additional users joining
        system_message_content = f"📞 {acceptor_name} joined the call"
        crud_chat.create_system_message(
            db=db,
            channel_id=video_call.channel_id,
            content=system_message_content,
            extra_data={"call_id": call_id, "call_status": "active", "user_joined": current_user.id}
        )

    # Generate token for the accepter
    token = get_livekit_token(video_call.room_name, current_user.email)

    # Broadcast acceptance/join to all channel members
    broadcast_type = "call_accepted" if is_first_accept else "user_joined_call"
    print(f"[ACCEPT CALL] Broadcasting {broadcast_type} to channel {video_call.channel_id}")

    await manager.broadcast(
        json.dumps({
            "type": broadcast_type,
            "call_id": call_id,
            "room_name": video_call.room_name,
            "livekit_url": settings.LIVEKIT_URL,
            "channel_id": video_call.channel_id,
            "caller_id": video_call.created_by_id,
            "accepted_by_id": current_user.id,
            "accepted_by_name": acceptor_name,
            "participant_count": len(video_call.joined_users) if video_call.joined_users else 1,
        }),
        str(video_call.channel_id)
    )

    print(f"[ACCEPT CALL] Success! Returning token for room {video_call.room_name}")

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
    print(f"[END CALL] Endpoint hit - call_id: {call_id}, user: {current_user.id} ({current_user.email})")

    video_call = crud_video_call.get_video_call_by_id(db, call_id=call_id)
    if not video_call:
        print(f"[END CALL] ERROR: Video call {call_id} not found in database")
        raise HTTPException(status_code=404, detail="Video call not found")

    print(f"[END CALL] Found call - status: {video_call.status}, channel: {video_call.channel_id}, room: {video_call.room_name}")

    # Get current participants in the call
    joined_users = video_call.joined_users if video_call.joined_users else []
    print(f"[END CALL] Current joined_users: {joined_users} (type: {type(joined_users)})")
    print(f"[END CALL] Current user leaving: {current_user.id} ({current_user.email})")
    print(f"[END CALL] Is current user in joined_users: {current_user.id in joined_users}")

    # Calculate how many users will remain after this user leaves
    remaining_users = [uid for uid in joined_users if uid != current_user.id]
    remaining_count = len(remaining_users)
    print(f"[END CALL] Remaining users after {current_user.id} leaves: {remaining_users}")
    print(f"[END CALL] Remaining count: {remaining_count}")

    user_name = current_user.first_name or current_user.email

    # If there are at least 2 other users still in the call, just remove this user
    # If only 1 user remains, end the call (can't have a call with just 1 person)
    if remaining_count > 1:
        print(f"[END CALL] Other users still in call - removing {current_user.id} from participants")

        # Remove this user from joined_users
        video_call = crud_video_call.remove_participant_from_video_call(db, video_call_id=call_id, user_id=current_user.id)

        # Create system message for user leaving
        system_message_content = f"📞 {user_name} left the call"
        crud_chat.create_system_message(
            db=db,
            channel_id=video_call.channel_id,
            content=system_message_content,
            extra_data={"call_id": call_id, "call_status": "active", "user_left": current_user.id}
        )
        print(f"[END CALL] System message created: {system_message_content}")

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
        print(f"[END CALL] Broadcasting user_left_call to channel {video_call.channel_id}: {broadcast_data}")

        await manager.broadcast(
            json.dumps(broadcast_data),
            str(video_call.channel_id)
        )
        print(f"[END CALL] Broadcast complete - user left")

        return {"status": "left", "participant_count": remaining_count}

    # This is the last user - end the call completely
    print(f"[END CALL] Last user leaving - ending call completely")

    # Update call status to completed
    video_call = crud_video_call.end_video_call(db, video_call_id=call_id)
    print(f"[END CALL] Updated call status to: {video_call.status}, ended_at: {video_call.ended_at}")

    # Calculate duration if answered_at exists
    duration_seconds = None
    if video_call.answered_at and video_call.ended_at:
        duration_seconds = int((video_call.ended_at - video_call.answered_at).total_seconds())

    print(f"[END CALL] Duration calculated: {duration_seconds} seconds")

    # Create system message in chat
    if duration_seconds:
        minutes = duration_seconds // 60
        seconds = duration_seconds % 60
        duration_str = f"{minutes}:{seconds:02d}" if minutes > 0 else f"{seconds}s"
        system_message_content = f"📞 Video call ended · Duration: {duration_str}"
    else:
        system_message_content = "📞 Video call ended"

    crud_chat.create_system_message(
        db=db,
        channel_id=video_call.channel_id,
        content=system_message_content,
        extra_data={"call_id": call_id, "call_status": "completed", "duration_seconds": duration_seconds}
    )
    print(f"[END CALL] System message created: {system_message_content}")

    # Broadcast call end to all channel members
    broadcast_data = {
        "type": "call_ended",
        "call_id": call_id,
        "room_name": video_call.room_name,
        "channel_id": video_call.channel_id,
        "ended_by_id": current_user.id,
        "duration_seconds": duration_seconds,
    }
    print(f"[END CALL] Broadcasting to channel {video_call.channel_id}: {broadcast_data}")

    await manager.broadcast(
        json.dumps(broadcast_data),
        str(video_call.channel_id)
    )
    print(f"[END CALL] Broadcast complete")

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
