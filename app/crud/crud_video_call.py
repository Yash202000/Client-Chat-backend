from sqlalchemy.orm import Session
from app.models.video_call import VideoCall
from app.schemas.video_call import VideoCallCreate
import uuid

def create_video_call(db: Session, *, obj_in: VideoCallCreate, created_by_id: int) -> VideoCall:
    room_name = str(uuid.uuid4())
    db_obj = VideoCall(
        room_name=room_name,
        channel_id=obj_in.channel_id,
        created_by_id=created_by_id,
        status="initiated",
        participants=[created_by_id]
    )
    db.add(db_obj)
    db.commit()
    db.refresh(db_obj)
    return db_obj

def get_active_video_call_by_channel(db: Session, *, channel_id: int) -> VideoCall:
    return db.query(VideoCall).filter(VideoCall.channel_id == channel_id, VideoCall.status == "active").first()

def update_video_call_status(db: Session, *, video_call_id: int, status: str) -> VideoCall:
    db_obj = db.query(VideoCall).get(video_call_id)
    if db_obj:
        db_obj.status = status
        db.commit()
        db.refresh(db_obj)
    return db_obj

def add_participant_to_video_call(db: Session, *, video_call_id: int, user_id: int) -> VideoCall:
    db_obj = db.query(VideoCall).get(video_call_id)
    if db_obj and user_id not in db_obj.participants:
        db_obj.participants.append(user_id)
        db.commit()
        db.refresh(db_obj)
    return db_obj
