
from sqlalchemy.orm import Session, joinedload
from app.models import user as models_user, role as models_role, permission as models_permission
from app.schemas import user as schemas_user
from app.core.security import get_password_hash
from app.services import user_settings_service
from app.schemas import user_settings as schemas_user_settings
import datetime
import asyncio
from typing import Dict, Callable

# Track pending offline tasks by user_id
_pending_offline_tasks: Dict[int, asyncio.Task] = {}
OFFLINE_GRACE_PERIOD = 5  # seconds

def get_user(db: Session, user_id: int):
    return db.query(models_user.User).options(joinedload(models_user.User.role).joinedload(models_role.Role.permissions)).filter(models_user.User.id == user_id).first()

def get_user_by_email(db: Session, email: str):
    return db.query(models_user.User).options(joinedload(models_user.User.role).joinedload(models_role.Role.permissions)).filter(models_user.User.email == email).first()

def get_users(db: Session, company_id: int, skip: int = 0, limit: int = 100):
    return db.query(models_user.User).options(joinedload(models_user.User.role).joinedload(models_role.Role.permissions)).filter(models_user.User.company_id == company_id).offset(skip).limit(limit).all()

from app.services import user_settings_service, company_service
from app.schemas import user_settings as schemas_user_settings, company as schemas_company

def create_user(db: Session, user: schemas_user.UserCreate, company_id: int, role_id: int = None, is_super_admin: bool = False):
    hashed_password = get_password_hash(user.password)

    db_user = models_user.User(
        email=user.email,
        hashed_password=hashed_password,
        company_id=company_id,
        first_name=user.first_name,
        last_name=user.last_name,
        phone_number=user.phone_number,
        job_title=user.job_title,
        profile_picture_url=user.profile_picture_url,
        is_active=True, # New users are active by default
        role_id=role_id,
        is_super_admin=is_super_admin
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)

    # Create default settings for the new user, linked to the company
    default_settings = schemas_user_settings.UserSettingsCreate()
    user_settings_service.create_user_settings(db, user_id=db_user.id, company_id=company_id, settings=default_settings)

    return db_user

def update_user(db: Session, db_obj: models_user.User, obj_in: schemas_user.UserUpdate):
    if isinstance(obj_in, dict):
        update_data = obj_in
    else:
        update_data = obj_in.model_dump(exclude_unset=True)

    if update_data.get("password"):
        hashed_password = get_password_hash(update_data["password"])
        del update_data["password"]
        update_data["hashed_password"] = hashed_password

    for field, value in update_data.items():
        setattr(db_obj, field, value)

    db.add(db_obj)
    db.commit()
    db.refresh(db_obj)
    return db_obj

def update_user_presence(db: Session, user_id: int, status: str):
    user = get_user(db, user_id)
    if user:
        user.presence_status = status
        if status == "offline":
            user.last_seen = datetime.datetime.now(datetime.UTC)
        db.commit()
        db.refresh(user)
        return user
    return None


async def schedule_offline_update(db_factory: Callable, user_id: int, grace_period: int = None):
    """
    Schedule a delayed offline update with grace period.
    Allows user to reconnect without going offline.
    Skips offline if user is in_call.

    Args:
        db_factory: Function to create a new DB session (e.g., SessionLocal)
        user_id: User ID to set offline
        grace_period: Seconds to wait before setting offline (default: OFFLINE_GRACE_PERIOD)
    """
    global _pending_offline_tasks

    if grace_period is None:
        grace_period = OFFLINE_GRACE_PERIOD

    # Cancel any existing pending task for this user
    if user_id in _pending_offline_tasks:
        _pending_offline_tasks[user_id].cancel()
        try:
            await _pending_offline_tasks[user_id]
        except asyncio.CancelledError:
            pass

    async def delayed_offline():
        try:
            await asyncio.sleep(grace_period)
            db = db_factory()
            try:
                user = get_user(db, user_id)
                if user:
                    # Don't set offline if user is in a call
                    if user.presence_status == "in_call":
                        print(f"[Presence] Skipping offline for user {user_id} - currently in_call")
                        return
                    # Don't set offline if user came back online
                    if user.presence_status == "online":
                        print(f"[Presence] Skipping offline for user {user_id} - already online")
                        return
                    user.presence_status = "offline"
                    user.last_seen = datetime.datetime.now(datetime.UTC)
                    db.commit()
                    print(f"[Presence] Set user {user_id} to offline after {grace_period}s grace period")
            finally:
                db.close()
        except asyncio.CancelledError:
            print(f"[Presence] Cancelled pending offline for user {user_id}")
        finally:
            _pending_offline_tasks.pop(user_id, None)

    task = asyncio.create_task(delayed_offline())
    _pending_offline_tasks[user_id] = task


def cancel_pending_offline(user_id: int):
    """
    Cancel pending offline task when user reconnects.

    Args:
        user_id: User ID to cancel offline for
    """
    global _pending_offline_tasks
    if user_id in _pending_offline_tasks:
        _pending_offline_tasks[user_id].cancel()
        _pending_offline_tasks.pop(user_id, None)
        print(f"[Presence] Cancelled pending offline for user {user_id} - reconnected")

def delete_user(db: Session, user_id: int):
    """Delete or deactivate a user by ID.
    If user has no dependencies, actually delete. Otherwise, soft delete (deactivate).
    Returns: dict with 'success' and 'action' ('deleted' or 'deactivated')
    """
    from app.models import (
        user_settings as models_user_settings,
        channel_membership as models_channel_membership,
        notification as models_notification,
        video_call as models_video_call,
        message_reaction as models_message_reaction,
        comment as models_comment,
        message_template as models_message_template,
        chat_attachment as models_chat_attachment,
        entity_note as models_entity_note,
        message_mention as models_message_mention,
        team_membership as models_team_membership,
        internal_chat_message as models_internal_chat_message,
        chat_message as models_chat_message,
        conversation_session as models_conversation_session,
    )

    user = get_user(db, user_id)
    if not user:
        return {"success": False, "action": None}

    # Check for dependencies (records that reference this user)
    has_dependencies = (
        db.query(models_channel_membership.ChannelMembership).filter(models_channel_membership.ChannelMembership.user_id == user_id).first() is not None or
        db.query(models_notification.Notification).filter(models_notification.Notification.user_id == user_id).first() is not None or
        db.query(models_video_call.VideoCall).filter(models_video_call.VideoCall.created_by_id == user_id).first() is not None or
        db.query(models_message_reaction.MessageReaction).filter(models_message_reaction.MessageReaction.user_id == user_id).first() is not None or
        db.query(models_comment.Comment).filter(models_comment.Comment.user_id == user_id).first() is not None or
        db.query(models_message_template.MessageTemplate).filter(models_message_template.MessageTemplate.created_by_user_id == user_id).first() is not None or
        db.query(models_chat_attachment.ChatAttachment).filter(models_chat_attachment.ChatAttachment.uploaded_by == user_id).first() is not None or
        db.query(models_entity_note.EntityNote).filter(models_entity_note.EntityNote.created_by == user_id).first() is not None or
        db.query(models_message_mention.MessageMention).filter(models_message_mention.MessageMention.mentioned_user_id == user_id).first() is not None or
        db.query(models_team_membership.TeamMembership).filter(models_team_membership.TeamMembership.user_id == user_id).first() is not None or
        db.query(models_internal_chat_message.InternalChatMessage).filter(models_internal_chat_message.InternalChatMessage.sender_id == user_id).first() is not None or
        db.query(models_chat_message.ChatMessage).filter(models_chat_message.ChatMessage.assignee_id == user_id).first() is not None or
        db.query(models_conversation_session.ConversationSession).filter(models_conversation_session.ConversationSession.assignee_id == user_id).first() is not None
    )

    if has_dependencies:
        # Soft delete - just deactivate
        user.is_active = False
        db.commit()
        return {"success": True, "action": "deactivated"}
    else:
        # No dependencies - can safely delete
        # Delete user settings first
        db.query(models_user_settings.UserSettings).filter(models_user_settings.UserSettings.user_id == user_id).delete()
        db.delete(user)
        db.commit()
        return {"success": True, "action": "deleted"}
