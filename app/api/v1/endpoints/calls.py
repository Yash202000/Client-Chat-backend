
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.dependencies import get_db
from app.core.config import settings
from livekit import api

from app.schemas.call import StartCallRequest

router = APIRouter()

@router.post("/start")
def start_call(request: StartCallRequest, db: Session = Depends(get_db)):
    # For now, we just return a success message.
    # In a real implementation, you might create a record of the call in the database.
    return {"message": f"Call started for session {request.session_id}"}

@router.get("/token")
def get_join_token(session_id: str, user_id: str, db: Session = Depends(get_db)):
    if not settings.LIVEKIT_URL or not settings.LIVEKIT_API_KEY or not settings.LIVEKIT_API_SECRET:
        raise HTTPException(status_code=500, detail="LiveKit is not configured.")

    token = api.AccessToken(
        settings.LIVEKIT_API_KEY,
        settings.LIVEKIT_API_SECRET
    ).with_identity(user_id).with_name(user_id).with_grants(
        api.VideoGrants(room_join=True, room=session_id)
    )

    return {"token": token.to_jwt()}
