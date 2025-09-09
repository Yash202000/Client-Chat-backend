from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from livekit import api
from app.core.config import settings
from sqlalchemy.orm import Session
from app.core.dependencies import get_db, get_current_user
from app.models.user import User
from app.crud import crud_video_call
from app.schemas.video_call import VideoCallCreate
from app.core.websockets import manager
import json

router = APIRouter()

class TokenRequest(BaseModel):
    room_name: str
    participant_name: str

def get_livekit_token(room_name: str, participant_name: str):
    if not settings.LIVEKIT_API_KEY or not settings.LIVEKIT_API_SECRET or not settings.LIVEKIT_URL:
        raise HTTPException(status_code=500, detail="LiveKit server not configured. Please check your .env file.")

    video_grant = api.VideoGrants(room=room_name, room_join=True, can_publish=True, can_subscribe=True)
    
    user_token = api.AccessToken(settings.LIVEKIT_API_KEY, settings.LIVEKIT_API_SECRET).with_identity(participant_name).with_name(participant_name).with_grants(video_grant)

    return user_token.to_jwt()

@router.post("/channels/{channel_id}/initiate")
async def initiate_video_call(
    channel_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    video_call = crud_video_call.create_video_call(db, obj_in=VideoCallCreate(channel_id=channel_id), created_by_id=current_user.id)
    crud_video_call.update_video_call_status(db, video_call_id=video_call.id, status="active")
    token = get_livekit_token(video_call.room_name, current_user.email)

    await manager.broadcast(
        json.dumps({
            "type": "video_call_initiated",
            "room_name": video_call.room_name,
            "livekit_token": token,
            "livekit_url": settings.LIVEKIT_URL,
            "channel_id": channel_id,
        }),
        str(channel_id)
    )

    return {"room_name": video_call.room_name, "livekit_token": token, "livekit_url": settings.LIVEKIT_URL}

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
    return {"room_name": video_call.room_name, "livekit_token": token, "livekit_url": settings.LIVEKIT_URL}

@router.get("/channels/{channel_id}/active")
def get_active_video_call(
    channel_id: int,
    db: Session = Depends(get_db),
):
    video_call = crud_video_call.get_active_video_call_by_channel(db, channel_id=channel_id)
    if not video_call:
        raise HTTPException(status_code=404, detail="No active video call found for this channel.")
    return {"room_name": video_call.room_name, "livekit_url": settings.LIVEKIT_URL}
