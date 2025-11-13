from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified
from app.models.video_call import VideoCall
from app.schemas.video_call import VideoCallCreate
from datetime import datetime
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
    return db.query(VideoCall).filter(
        VideoCall.channel_id == channel_id,
        VideoCall.status.in_(["ringing", "active"])
    ).first()

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

def add_user_to_joined_users(db: Session, *, video_call_id: int, user_id: int) -> VideoCall:
    """Add a user to joined_users list without changing call status"""
    db_obj = db.query(VideoCall).get(video_call_id)
    if db_obj:
        if db_obj.joined_users is None:
            db_obj.joined_users = []
        if user_id not in db_obj.joined_users:
            db_obj.joined_users.append(user_id)
            # Mark the field as modified to ensure SQLAlchemy tracks the change
            flag_modified(db_obj, "joined_users")
        db.commit()
        db.refresh(db_obj)
    return db_obj

def get_video_call_by_id(db: Session, *, call_id: int) -> VideoCall:
    return db.query(VideoCall).get(call_id)

def get_ringing_call_by_channel(db: Session, *, channel_id: int) -> VideoCall:
    return db.query(VideoCall).filter(
        VideoCall.channel_id == channel_id,
        VideoCall.status == "ringing"
    ).first()

def reject_video_call(db: Session, *, video_call_id: int, rejected_by_id: int) -> VideoCall:
    db_obj = db.query(VideoCall).get(video_call_id)
    if db_obj:
        db_obj.status = "rejected"
        db_obj.ended_at = datetime.utcnow()
        db.commit()
        db.refresh(db_obj)
    return db_obj

def accept_video_call(db: Session, *, video_call_id: int, accepted_by_id: int) -> VideoCall:
    db_obj = db.query(VideoCall).get(video_call_id)
    if db_obj:
        db_obj.status = "active"
        db_obj.answered_at = datetime.utcnow()
        # Add to joined_users if not already present
        if db_obj.joined_users is None:
            db_obj.joined_users = []
        if accepted_by_id not in db_obj.joined_users:
            db_obj.joined_users.append(accepted_by_id)
            # Mark the field as modified to ensure SQLAlchemy tracks the change
            flag_modified(db_obj, "joined_users")
        db.commit()
        db.refresh(db_obj)
    return db_obj

def remove_participant_from_video_call(db: Session, *, video_call_id: int, user_id: int) -> VideoCall:
    """Remove a user from joined_users list when they leave the call"""
    db_obj = db.query(VideoCall).get(video_call_id)
    if db_obj and db_obj.joined_users and user_id in db_obj.joined_users:
        db_obj.joined_users.remove(user_id)
        # Mark the field as modified to ensure SQLAlchemy tracks the change
        flag_modified(db_obj, "joined_users")
        db.commit()
        db.refresh(db_obj)
    return db_obj

def end_video_call(db: Session, *, video_call_id: int) -> VideoCall:
    db_obj = db.query(VideoCall).get(video_call_id)
    if db_obj:
        db_obj.status = "completed"
        db_obj.ended_at = datetime.utcnow()
        db.commit()
        db.refresh(db_obj)
    return db_obj

def mark_call_as_missed(db: Session, *, video_call_id: int) -> VideoCall:
    db_obj = db.query(VideoCall).get(video_call_id)
    if db_obj and db_obj.status == "ringing":
        db_obj.status = "missed"
        db_obj.ended_at = datetime.utcnow()
        db.commit()
        db.refresh(db_obj)
    return db_obj

def get_call_history(db: Session, *, channel_id: int, limit: int = 50) -> list[VideoCall]:
    return db.query(VideoCall).filter(
        VideoCall.channel_id == channel_id
    ).order_by(VideoCall.started_at.desc()).limit(limit).all()
