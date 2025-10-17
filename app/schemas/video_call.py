from pydantic import BaseModel

class VideoCallCreate(BaseModel):
    channel_id: int
    
class VideoCallInitiateResponse(BaseModel):
    room_name: str
    livekit_token: str
    livekit_url: str

class VideoCallJoinResponse(BaseModel):
    room_name: str
    livekit_token: str
    livekit_url: str