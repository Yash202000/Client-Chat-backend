
from sqlalchemy.orm import Session
from app.models import ChatChannel, ChannelMembership, InternalChatMessage, ChatAttachment, MessageReaction, MessageMention, User, Team
from app.schemas import chat as chat_schema
from typing import List, Optional
import re
from app.crud import crud_notification

# CRUD for ChatChannel
def create_channel(db: Session, channel: chat_schema.ChatChannelCreate, creator_id: int, company_id: int) -> ChatChannel:
    db_channel = ChatChannel(**channel.model_dump(), creator_id=creator_id, company_id=company_id)
    db.add(db_channel)
    db.commit()
    db.refresh(db_channel)
    # Automatically add the creator as a member
    add_user_to_channel(db, user_id=creator_id, channel_id=db_channel.id)
    return db_channel

def get_channel(db: Session, channel_id: int) -> Optional[ChatChannel]:
    return db.query(ChatChannel).filter(ChatChannel.id == channel_id).first()

def get_user_channels(db: Session, user_id: int) -> List[ChatChannel]:
    return db.query(ChatChannel).join(ChannelMembership).filter(ChannelMembership.user_id == user_id).all()

# CRUD for ChannelMembership
def add_user_to_channel(db: Session, user_id: int, channel_id: int) -> ChannelMembership:
    db_membership = ChannelMembership(user_id=user_id, channel_id=channel_id)
    db.add(db_membership)
    db.commit()
    db.refresh(db_membership)
    return db_membership

def remove_user_from_channel(db: Session, user_id: int, channel_id: int):
    db.query(ChannelMembership).filter(ChannelMembership.user_id == user_id, ChannelMembership.channel_id == channel_id).delete()
    db.commit()

def get_channel_members(db: Session, channel_id: int) -> List[User]:
    return db.query(User).join(ChannelMembership).filter(ChannelMembership.channel_id == channel_id).all()

# Helper function to parse mentions from message content
def parse_mentions(content: str) -> List[int]:
    """Extract user IDs from @mentions in format @user:123"""
    mention_pattern = r'@user:(\d+)'
    matches = re.findall(mention_pattern, content)
    return [int(user_id) for user_id in matches]

# CRUD for InternalChatMessage
def create_message(db: Session, message: chat_schema.InternalChatMessageCreate, sender_id: int) -> InternalChatMessage:
    db_message = InternalChatMessage(
        content=message.content,
        channel_id=message.channel_id,
        sender_id=sender_id,
        parent_message_id=message.parent_message_id
    )
    db.add(db_message)
    db.commit()
    db.refresh(db_message)

    # Parse and create mentions
    mentioned_user_ids = parse_mentions(message.content)
    for mentioned_user_id in mentioned_user_ids:
        mention = MessageMention(message_id=db_message.id, mentioned_user_id=mentioned_user_id)
        db.add(mention)

    if mentioned_user_ids:
        db.commit()
        db.refresh(db_message)

        # Create mention notifications
        crud_notification.create_mention_notifications(
            db=db,
            mentioned_user_ids=mentioned_user_ids,
            message_id=db_message.id,
            channel_id=message.channel_id,
            actor_id=sender_id,
            message_preview=message.content
        )

    # If this is a reply, notify the parent message author
    if message.parent_message_id:
        parent_message = get_message_by_id(db, message.parent_message_id)
        if parent_message and parent_message.sender_id != sender_id:
            crud_notification.create_reply_notification(
                db=db,
                parent_message_sender_id=parent_message.sender_id,
                reply_message_id=db_message.id,
                channel_id=message.channel_id,
                actor_id=sender_id,
                message_preview=message.content
            )

    return db_message

def create_system_message(db: Session, channel_id: int, content: str, extra_data: dict = None) -> InternalChatMessage:
    """Create a system message (e.g., for call events)"""
    # Use sender_id = 0 or the first user in the channel for system messages
    # Or we can use extra_data to mark it as a system message
    channel = get_channel(db, channel_id)
    if not channel:
        return None

    # Get the first member as the "sender" for system messages
    # This is just for foreign key constraint; we'll mark it as system in extra_data
    members = get_channel_members(db, channel_id)
    sender_id = members[0].id if members else 1  # Fallback to user ID 1

    message_extra_data = extra_data or {}
    message_extra_data['is_system'] = True

    db_message = InternalChatMessage(
        content=content,
        channel_id=channel_id,
        sender_id=sender_id,
        extra_data=message_extra_data
    )
    db.add(db_message)
    db.commit()
    db.refresh(db_message)

    return db_message

def get_channel_messages(db: Session, channel_id: int, skip: int = 0, limit: int = 100) -> List[InternalChatMessage]:
    # Only get top-level messages (not replies)
    return db.query(InternalChatMessage).filter(
        InternalChatMessage.channel_id == channel_id,
        InternalChatMessage.parent_message_id == None
    ).order_by(InternalChatMessage.created_at.asc()).offset(skip).limit(limit).all()

def get_message_replies(db: Session, message_id: int, skip: int = 0, limit: int = 50) -> List[InternalChatMessage]:
    """Get all replies to a specific message"""
    return db.query(InternalChatMessage).filter(
        InternalChatMessage.parent_message_id == message_id
    ).order_by(InternalChatMessage.created_at.asc()).offset(skip).limit(limit).all()

def get_message_by_id(db: Session, message_id: int) -> Optional[InternalChatMessage]:
    """Get a specific message by ID"""
    return db.query(InternalChatMessage).filter(InternalChatMessage.id == message_id).first()

def get_reply_count(db: Session, message_id: int) -> int:
    """Get count of replies for a message"""
    return db.query(InternalChatMessage).filter(InternalChatMessage.parent_message_id == message_id).count()

# CRUD for ChatAttachment
def create_attachment(db: Session, attachment: chat_schema.ChatAttachmentCreate) -> ChatAttachment:
    db_attachment = ChatAttachment(**attachment.model_dump())
    db.add(db_attachment)
    db.commit()
    db.refresh(db_attachment)
    return db_attachment

def get_message_attachments(db: Session, message_id: int) -> List[ChatAttachment]:
    return db.query(ChatAttachment).filter(ChatAttachment.message_id == message_id).all()

def delete_attachment(db: Session, attachment_id: int):
    db.query(ChatAttachment).filter(ChatAttachment.id == attachment_id).delete()
    db.commit()

# CRUD for MessageReaction
def add_reaction(db: Session, message_id: int, user_id: int, emoji: str) -> MessageReaction:
    """Add a reaction to a message. If it already exists, return the existing one."""
    # Check if reaction already exists
    existing_reaction = db.query(MessageReaction).filter(
        MessageReaction.message_id == message_id,
        MessageReaction.user_id == user_id,
        MessageReaction.emoji == emoji
    ).first()

    if existing_reaction:
        return existing_reaction

    db_reaction = MessageReaction(message_id=message_id, user_id=user_id, emoji=emoji)
    db.add(db_reaction)
    db.commit()
    db.refresh(db_reaction)
    return db_reaction

def remove_reaction(db: Session, message_id: int, user_id: int, emoji: str) -> bool:
    """Remove a reaction from a message. Returns True if deleted, False if not found."""
    result = db.query(MessageReaction).filter(
        MessageReaction.message_id == message_id,
        MessageReaction.user_id == user_id,
        MessageReaction.emoji == emoji
    ).delete()
    db.commit()
    return result > 0

def get_message_reactions(db: Session, message_id: int) -> List[MessageReaction]:
    """Get all reactions for a message"""
    return db.query(MessageReaction).filter(MessageReaction.message_id == message_id).all()

# CRUD for Message Search
def search_messages(db: Session, channel_id: int, query: str, skip: int = 0, limit: int = 50) -> List[InternalChatMessage]:
    """
    Search messages in a channel by content (case-insensitive).
    Returns both top-level messages and replies that match the query.
    """
    return db.query(InternalChatMessage).filter(
        InternalChatMessage.channel_id == channel_id,
        InternalChatMessage.content.ilike(f'%{query}%')
    ).order_by(InternalChatMessage.created_at.desc()).offset(skip).limit(limit).all()
