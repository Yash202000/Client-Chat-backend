
from sqlalchemy.orm import Session
from app.models import Notification, User
from typing import List, Optional
from datetime import datetime
from app.services.connection_manager import manager
import json
import asyncio

def create_notification(
    db: Session,
    user_id: int,
    notification_type: str,
    title: str,
    message: str,
    related_message_id: Optional[int] = None,
    related_channel_id: Optional[int] = None,
    actor_id: Optional[int] = None
) -> Notification:
    """Create a new notification"""
    notification = Notification(
        user_id=user_id,
        notification_type=notification_type,
        title=title,
        message=message,
        related_message_id=related_message_id,
        related_channel_id=related_channel_id,
        actor_id=actor_id,
        is_read=False
    )
    db.add(notification)
    db.commit()
    db.refresh(notification)

    # Broadcast unread count to user via WebSocket
    _broadcast_unread_count(db, user_id)

    return notification

def get_user_notifications(
    db: Session,
    user_id: int,
    skip: int = 0,
    limit: int = 50,
    unread_only: bool = False
) -> List[Notification]:
    """Get notifications for a user"""
    query = db.query(Notification).filter(Notification.user_id == user_id)

    if unread_only:
        query = query.filter(Notification.is_read == False)

    return query.order_by(Notification.created_at.desc()).offset(skip).limit(limit).all()

def get_unread_count(db: Session, user_id: int) -> int:
    """Get count of unread notifications for a user"""
    return db.query(Notification).filter(
        Notification.user_id == user_id,
        Notification.is_read == False
    ).count()

def mark_notification_as_read(db: Session, notification_id: int, user_id: int) -> bool:
    """Mark a notification as read"""
    notification = db.query(Notification).filter(
        Notification.id == notification_id,
        Notification.user_id == user_id
    ).first()

    if notification:
        notification.is_read = True
        notification.read_at = datetime.utcnow()
        db.commit()

        # Broadcast updated unread count to user via WebSocket
        _broadcast_unread_count(db, user_id)

        return True
    return False

def mark_all_as_read(db: Session, user_id: int) -> int:
    """Mark all notifications as read for a user. Returns count of updated notifications."""
    count = db.query(Notification).filter(
        Notification.user_id == user_id,
        Notification.is_read == False
    ).update({
        "is_read": True,
        "read_at": datetime.utcnow()
    })
    db.commit()

    # Broadcast updated unread count to user via WebSocket
    if count > 0:
        _broadcast_unread_count(db, user_id)

    return count

def delete_notification(db: Session, notification_id: int, user_id: int) -> bool:
    """Delete a notification"""
    result = db.query(Notification).filter(
        Notification.id == notification_id,
        Notification.user_id == user_id
    ).delete()
    db.commit()
    return result > 0

# Helper function to create mention notifications
def create_mention_notifications(
    db: Session,
    mentioned_user_ids: List[int],
    message_id: int,
    channel_id: int,
    actor_id: int,
    message_preview: str
) -> None:
    """Create notifications for mentioned users"""
    # Get actor details
    actor = db.query(User).filter(User.id == actor_id).first()
    actor_name = actor.first_name if actor and actor.first_name else "Someone"

    # Replace @user:X mentions with actual names
    import re
    def replace_mention(match):
        user_id = int(match.group(1))
        mentioned_user = db.query(User).filter(User.id == user_id).first()
        if mentioned_user:
            return f"@{mentioned_user.first_name or mentioned_user.email.split('@')[0]}"
        return match.group(0)

    preview = re.sub(r'@user:(\d+)', replace_mention, message_preview)

    # Truncate message preview
    preview = preview[:100] + "..." if len(preview) > 100 else preview

    for user_id in mentioned_user_ids:
        # Don't notify if the actor is mentioning themselves
        if user_id != actor_id:
            create_notification(
                db=db,
                user_id=user_id,
                notification_type="mention",
                title=f"{actor_name} mentioned you",
                message=preview,
                related_message_id=message_id,
                related_channel_id=channel_id,
                actor_id=actor_id
            )

# Helper function to create reply notifications
def create_reply_notification(
    db: Session,
    parent_message_sender_id: int,
    reply_message_id: int,
    channel_id: int,
    actor_id: int,
    message_preview: str
) -> None:
    """Create notification for thread reply"""
    # Don't notify if the actor is replying to their own message
    if parent_message_sender_id == actor_id:
        return

    # Get actor details
    actor = db.query(User).filter(User.id == actor_id).first()
    actor_name = actor.first_name if actor and actor.first_name else "Someone"

    # Truncate message preview
    preview = message_preview[:100] + "..." if len(message_preview) > 100 else message_preview

    create_notification(
        db=db,
        user_id=parent_message_sender_id,
        notification_type="reply",
        title=f"{actor_name} replied to your message",
        message=preview,
        related_message_id=reply_message_id,
        related_channel_id=channel_id,
        actor_id=actor_id
    )

def _broadcast_unread_count(db: Session, user_id: int) -> None:
    """Helper function to broadcast unread count to user via WebSocket"""
    try:
        # Get the user to find their company_id
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return

        # Get current unread count
        unread_count = get_unread_count(db, user_id)

        # Broadcast to company WebSocket with user_id filter
        asyncio.create_task(
            manager.broadcast(
                json.dumps({
                    "type": "unread_count_update",
                    "user_id": user_id,  # Frontend will filter by this
                    "unread_count": unread_count
                }),
                str(user.company_id)
            )
        )
        print(f"[Notification] Broadcasted unread count ({unread_count}) to user {user_id}")
    except Exception as e:
        print(f"[Notification] Error broadcasting unread count: {e}")

# Helper function to create missed call notifications
def create_missed_call_notification(
    db: Session,
    user_id: int,
    call_id: int,
    channel_id: int,
    caller_id: int,
    caller_name: str
) -> None:
    """Create notification for missed call"""
    # Don't notify the caller themselves
    if user_id == caller_id:
        return

    create_notification(
        db=db,
        user_id=user_id,
        notification_type="missed_call",
        title=f"Missed call from {caller_name}",
        message=f"You missed a video call from {caller_name}",
        related_channel_id=channel_id,
        actor_id=caller_id
    )


def create_handoff_call_notification(
    db: Session,
    agent_user_id: int,
    session_id: str,
    customer_name: str,
    reason: str,
    priority: str
) -> Notification:
    """Create notification for incoming handoff call from customer"""
    title = f"Incoming call from {customer_name}"
    message = f"Session: {session_id}. Reason: {reason}. Priority: {priority}"

    return create_notification(
        db=db,
        user_id=agent_user_id,
        notification_type="handoff_call",
        title=title,
        message=message,
        related_message_id=None,
        related_channel_id=None,
        actor_id=None
    )
