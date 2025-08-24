from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.dependencies import get_db
from livekit import AccessToken, VideoGrant
import os

router = APIRouter()

LIVEKIT_API_KEY = os.environ.get("LIVEKIT_API_KEY")
LIVEKIT_API_SECRET = os.environ.get("LIVEKIT_API_SECRET")
LIVEKIT_URL = os.environ.get("LIVEKIT_URL")

@router.post("/token")
async def create_livekit_token(room_name: str, identity: str):
    if not all([LIVEKIT_API_KEY, LIVEKIT_API_SECRET, LIVEKIT_URL]):
        raise HTTPException(status_code=500, detail="LiveKit server not configured.")

    at = AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET, identity=identity)
    at.add_grant(VideoGrant(room=room_name, can_publish=True, can_subscribe=True))

    return {"token": at.to_jwt(), "livekitUrl": LIVEKIT_URL}
