
import os
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Optional
from livekit import api
from sqlalchemy import func

from app.core.dependencies import get_db
from app.crud import crud_chat
from app.models import User, VideoCall
from app.core.auth import get_current_user
from app.schemas.video_call import VideoCallInitiateResponse, VideoCallJoinResponse

router = APIRouter()

LIVEKIT_URL = os.getenv("LIVEKIT_URL")
LIVEKIT_API_KEY = os.getenv("LIVEKIT_API_KEY")
LIVEKIT_API_SECRET = os.getenv("LIVEKIT_API_SECRET")

@router.post("/channels/{channel_id}/initiate", response_model=VideoCallInitiateResponse)
async def initiate_video_call(
    channel_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not all([LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET]):
        raise HTTPException(status_code=500, detail="LiveKit configuration missing.")

    # Check if an active video call already exists for this channel
    existing_call = db.query(VideoCall).filter(
        VideoCall.channel_id == channel_id,
        VideoCall.status == "active"
    ).first()

    room_name = f"channel-{channel_id}"
    
    if existing_call:
        # If call exists, update participants and generate token for joining
        # For simplicity, we'll just generate a token for the existing room
        # In a real app, you might update existing_call.participants JSONB field
        pass
    else:
        # Create a new video call entry
        new_call = VideoCall(
            room_name=room_name,
            channel_id=channel_id,
            created_by_id=current_user.id,
            status="active"
        )
        db.add(new_call)
        db.commit()
        db.refresh(new_call)

    # Generate LiveKit token
    grant = api.VideoGrant(room_join=True, room=room_name)
    token = api.AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET).with_identity(str(current_user.id)).with_name(current_user.full_name).with_grant(grant)
    livekit_token = token.to_jwt()

    return VideoCallInitiateResponse(
        room_name=room_name,
        livekit_token=livekit_token,
        livekit_url=LIVEKIT_URL
    )

@router.post("/channels/{channel_id}/join", response_model=VideoCallJoinResponse)
async def join_video_call(
    channel_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not all([LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET]):
        raise HTTPException(status_code=500, detail="LiveKit configuration missing.")

    # Check if an active video call exists for this channel
    existing_call = db.query(VideoCall).filter(
        VideoCall.channel_id == channel_id,
        VideoCall.status == "active"
    ).first()

    if not existing_call:
        raise HTTPException(status_code=404, detail="No active video call found for this channel.")

    room_name = existing_call.room_name

    # Generate LiveKit token for joining
    grant = api.VideoGrant(room_join=True, room=room_name)
    token = api.AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET).with_identity(str(current_user.id)).with_name(current_user.full_name).with_grant(grant)
    livekit_token = token.to_jwt()

    return VideoCallJoinResponse(
        room_name=room_name,
        livekit_token=livekit_token,
        livekit_url=LIVEKIT_URL
    )

@router.get("/channels/{channel_id}/active", response_model=Optional[VideoCallInitiateResponse])
async def get_active_video_call(
    channel_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    existing_call = db.query(VideoCall).filter(
        VideoCall.channel_id == channel_id,
        VideoCall.status == "active"
    ).first()

    if not existing_call:
        raise HTTPException(status_code=404, detail="No active video call found for this channel.")
    
    # Generate a token for the current user to join the existing call
    grant = api.VideoGrant(room_join=True, room=existing_call.room_name)
    token = api.AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET).with_identity(str(current_user.id)).with_name(current_user.full_name).with_grant(grant)
    livekit_token = token.to_jwt()

    return VideoCallInitiateResponse(
        room_name=existing_call.room_name,
        livekit_token=livekit_token,
        livekit_url=LIVEKIT_URL
    )

@router.post("/{call_id}/end")
async def end_video_call(
    call_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    video_call = db.query(VideoCall).filter(VideoCall.id == call_id).first()
    if not video_call:
        raise HTTPException(status_code=404, detail="Video call not found.")
    
    # Only the creator or an admin should be able to end the call
    # For simplicity, we'll allow creator for now
    if video_call.created_by_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to end this call.")

    video_call.status = "completed"
    video_call.ended_at = func.now()
    db.add(video_call)
    db.commit()
    db.refresh(video_call)
    
    return {"message": "Video call ended successfully."}
