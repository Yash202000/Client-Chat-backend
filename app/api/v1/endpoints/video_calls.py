from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from livekit import api
from app.core.config import settings

router = APIRouter()

class TokenRequest(BaseModel):
    room_name: str
    participant_name: str
    agent_id: str

@router.post("/token")
async def get_livekit_token(request: TokenRequest):
    if not settings.LIVEKIT_API_KEY or not settings.LIVEKIT_API_SECRET or not settings.LIVEKIT_URL:
        raise HTTPException(status_code=500, detail="LiveKit server not configured. Please check your .env file.")

    # Create a token for the user
    video_grant = api.VideoGrants(room=request.room_name, room_join=True, can_publish=True, can_subscribe=True)
    
    user_token = api.AccessToken(settings.LIVEKIT_API_KEY, settings.LIVEKIT_API_SECRET).with_identity(request.participant_name).with_name(request.participant_name).with_grants(video_grant)

    # TODO: Update agent dispatch logic
    # # Dispatch an agent to the room
    # try:
    #     livekit_api = api.LiveKitAPI(host=settings.LIVEKIT_URL, api_key=settings.LIVEKIT_API_KEY, api_secret=settings.LIVEKIT_API_SECRET)
        
    #     agent_identity = f"agent-{request.agent_id}"
        
    #     job = agent.Job(
    #         id=request.room_name,
    #         type=agent.JobType.JT_ROOM,
    #         room=agent.Room(name=request.room_name),
    #         participant=agent.Participant(identity=agent_identity),
    #     )
        
    #     dispatch = agent.Dispatch(
    #         job=job,
    #         agent=agent.Agent(identity=agent_identity)
    #     )
        
    #     await livekit_api.agent_dispatch.dispatch(dispatch)
        
    # except Exception as e:
    #     print(f"Error dispatching agent: {e}")
    #     # We don't want to fail the user's token generation if agent dispatch fails
    #     pass
    # finally:
    #     if 'livekit_api' in locals():
    #         await livekit_api.aclose()


    return {"access_token": user_token.to_jwt()}
