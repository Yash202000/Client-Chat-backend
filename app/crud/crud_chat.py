
from sqlalchemy.orm import Session, joinedload, selectinload
from sqlalchemy import func
from app.models import ChatChannel, ChannelMembership, InternalChatMessage, ChatAttachment, MessageReaction, MessageMention, User, Team
from app.models.pinned_message import PinnedMessage
from app.models.message_read import MessageRead
from app.schemas import chat as chat_schema
from typing import List, Optional
import re
import datetime
from app.crud import crud_notification

# CRUD for ChatChannel
def find_existing_dm(db: Session, user_id_1: int, user_id_2: int, company_id: int) -> Optional[ChatChannel]:
    """Return existing 1-on-1 DM channel between exactly two users, or None."""
    user1_channels = db.query(ChannelMembership.channel_id).filter(ChannelMembership.user_id == user_id_1)
    user2_channels = db.query(ChannelMembership.channel_id).filter(ChannelMembership.user_id == user_id_2)
    # Subquery: channels with exactly 2 members
    exact_two = (
        db.query(ChannelMembership.channel_id)
        .group_by(ChannelMembership.channel_id)
        .having(func.count(ChannelMembership.user_id) == 2)
        .subquery()
    )
    row = (
        db.query(ChatChannel.id)
        .filter(
            ChatChannel.id.in_(user1_channels),
            ChatChannel.id.in_(user2_channels),
            ChatChannel.id.in_(exact_two),
            ChatChannel.channel_type == 'DM',
            ChatChannel.company_id == company_id,
        )
        .first()
    )
    if row:
        return db.query(ChatChannel).filter(ChatChannel.id == row[0]).first()
    return None


def create_channel(db: Session, channel: chat_schema.ChatChannelCreate, creator_id: int, company_id: int) -> ChatChannel:
    # For DM channels with exactly one other member, return existing DM if found
    if channel.channel_type and channel.channel_type.upper() == 'DM' and len(channel.member_ids or []) == 1:
        other_id = channel.member_ids[0]
        existing = find_existing_dm(db, creator_id, other_id, company_id)
        if existing:
            return existing

    channel_data = channel.model_dump(exclude={"member_ids"})
    db_channel = ChatChannel(**channel_data, creator_id=creator_id, company_id=company_id)
    db.add(db_channel)
    db.commit()
    db.refresh(db_channel)
    # Automatically add the creator as a member
    add_user_to_channel(db, user_id=creator_id, channel_id=db_channel.id)
    # Add additional members
    for user_id in (channel.member_ids or []):
        if user_id != creator_id:
            add_user_to_channel(db, user_id=user_id, channel_id=db_channel.id)
    return db_channel


def rename_channel(db: Session, channel_id: int, name: str) -> Optional[ChatChannel]:
    db_channel = db.query(ChatChannel).filter(ChatChannel.id == channel_id).first()
    if not db_channel:
        return None
    db_channel.name = name
    db.commit()
    db.refresh(db_channel)
    return db_channel

def get_channel(db: Session, channel_id: int) -> Optional[ChatChannel]:
    return db.query(ChatChannel).filter(ChatChannel.id == channel_id).first()

def get_user_channels(db: Session, user_id: int) -> List[ChatChannel]:
    return (
        db.query(ChatChannel)
        .join(ChannelMembership)
        .filter(ChannelMembership.user_id == user_id)
        .options(selectinload(ChatChannel.participants).joinedload(ChannelMembership.user))
        .all()
    )


def get_user_channels_with_summary(db: Session, user_id: int) -> list:
    """Returns channels enriched with last_message preview and unread_count."""
    channels = (
        db.query(ChatChannel)
        .join(ChannelMembership)
        .filter(ChannelMembership.user_id == user_id)
        .options(selectinload(ChatChannel.participants).joinedload(ChannelMembership.user))
        .all()
    )

    result = []
    for channel in channels:
        # Last non-scheduled message
        last_msg = (
            db.query(InternalChatMessage)
            .options(joinedload(InternalChatMessage.sender))
            .filter(
                InternalChatMessage.channel_id == channel.id,
                InternalChatMessage.scheduled_at.is_(None),
            )
            .order_by(InternalChatMessage.created_at.desc())
            .first()
        )

        # Unread count: messages NOT read by this user and NOT sent by this user
        unread_count = (
            db.query(func.count(InternalChatMessage.id))
            .filter(
                InternalChatMessage.channel_id == channel.id,
                InternalChatMessage.sender_id != user_id,
                InternalChatMessage.scheduled_at.is_(None),
                ~db.query(MessageRead).filter(
                    MessageRead.message_id == InternalChatMessage.id,
                    MessageRead.user_id == user_id,
                ).exists()
            )
            .scalar() or 0
        )

        last_message_data = None
        if last_msg:
            sender = last_msg.sender
            sender_name = (
                f"{sender.first_name or ''} {sender.last_name or ''}".strip()
                or sender.email
            )
            is_activity = bool(
                last_msg.extra_data and last_msg.extra_data.get('is_activity')
            )
            last_message_data = {
                "id": last_msg.id,
                "content": last_msg.content,
                "sender_id": last_msg.sender_id,
                "sender_name": sender_name,
                "created_at": last_msg.created_at,
                "is_activity": is_activity,
            }

        result.append({
            "channel": channel,
            "last_message": last_message_data,
            "unread_count": unread_count,
        })

    # Sort by last message time descending, fall back to channel creation time
    result.sort(
        key=lambda x: (
            x["last_message"]["created_at"]
            if x["last_message"]
            else x["channel"].created_at
        ),
        reverse=True,
    )
    return result

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
    extra = {"is_activity": True} if message.is_activity else None
    db_message = InternalChatMessage(
        content=message.content,
        channel_id=message.channel_id,
        sender_id=sender_id,
        parent_message_id=message.parent_message_id,
        scheduled_at=message.scheduled_at,
        extra_data=extra,
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
    # Fetch latest `limit` messages by ordering DESC, then reverse to return chronological order
    rows = (
        db.query(InternalChatMessage)
        .filter(
            InternalChatMessage.channel_id == channel_id,
            InternalChatMessage.parent_message_id == None,
        )
        .options(
            selectinload(InternalChatMessage.attachments),
            selectinload(InternalChatMessage.reactions),
            joinedload(InternalChatMessage.sender),
        )
        .order_by(InternalChatMessage.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    rows = list(reversed(rows))
    return rows

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


# ── Pinned Messages ────────────────────────────────────────────────────────────

def pin_message(db: Session, channel_id: int, message_id: int, user_id: int) -> Optional[PinnedMessage]:
    existing = db.query(PinnedMessage).filter(
        PinnedMessage.channel_id == channel_id,
        PinnedMessage.message_id == message_id,
    ).first()
    if existing:
        return existing
    pin = PinnedMessage(channel_id=channel_id, message_id=message_id, pinned_by_user_id=user_id)
    db.add(pin)
    db.commit()
    db.refresh(pin)
    return pin


def unpin_message(db: Session, channel_id: int, message_id: int) -> bool:
    result = db.query(PinnedMessage).filter(
        PinnedMessage.channel_id == channel_id,
        PinnedMessage.message_id == message_id,
    ).delete()
    db.commit()
    return result > 0


def get_pinned_messages(db: Session, channel_id: int) -> List[PinnedMessage]:
    return (
        db.query(PinnedMessage)
        .filter(PinnedMessage.channel_id == channel_id)
        .options(joinedload(PinnedMessage.message), joinedload(PinnedMessage.pinned_by))
        .order_by(PinnedMessage.pinned_at.desc())
        .all()
    )


# ── Read Receipts ──────────────────────────────────────────────────────────────

def mark_message_read(db: Session, message_id: int, user_id: int) -> MessageRead:
    existing = db.query(MessageRead).filter(
        MessageRead.message_id == message_id,
        MessageRead.user_id == user_id,
    ).first()
    if existing:
        return existing
    read = MessageRead(message_id=message_id, user_id=user_id)
    db.add(read)
    db.commit()
    db.refresh(read)
    return read


def mark_channel_read(db: Session, channel_id: int, user_id: int):
    """Mark all unread messages in a channel as read for a user."""
    messages = db.query(InternalChatMessage).filter(
        InternalChatMessage.channel_id == channel_id,
        ~InternalChatMessage.id.in_(
            db.query(MessageRead.message_id).filter(MessageRead.user_id == user_id)
        )
    ).all()
    for msg in messages:
        read = MessageRead(message_id=msg.id, user_id=user_id)
        db.add(read)
    if messages:
        db.commit()


def get_message_reads(db: Session, message_id: int) -> List[MessageRead]:
    return (
        db.query(MessageRead)
        .filter(MessageRead.message_id == message_id)
        .options(joinedload(MessageRead.user))
        .order_by(MessageRead.read_at.asc())
        .all()
    )


def get_channel_read_map(db: Session, channel_id: int) -> dict:
    """Returns {message_id: [MessageRead, ...]} for the channel's latest messages."""
    reads = (
        db.query(MessageRead)
        .join(InternalChatMessage, MessageRead.message_id == InternalChatMessage.id)
        .filter(InternalChatMessage.channel_id == channel_id)
        .options(joinedload(MessageRead.user))
        .all()
    )
    result: dict = {}
    for r in reads:
        result.setdefault(r.message_id, []).append(r)
    return result


# ── Scheduled Messages ─────────────────────────────────────────────────────────

def get_scheduled_messages(db: Session, user_id: int) -> List[InternalChatMessage]:
    return (
        db.query(InternalChatMessage)
        .filter(
            InternalChatMessage.sender_id == user_id,
            InternalChatMessage.scheduled_at != None,
            InternalChatMessage.scheduled_at > datetime.datetime.utcnow(),
        )
        .order_by(InternalChatMessage.scheduled_at.asc())
        .all()
    )


def dispatch_due_scheduled_messages(db: Session):
    """Send all scheduled messages whose time has come. Returns dispatched messages."""
    now = datetime.datetime.utcnow()
    due = db.query(InternalChatMessage).filter(
        InternalChatMessage.scheduled_at != None,
        InternalChatMessage.scheduled_at <= now,
    ).all()
    for msg in due:
        msg.scheduled_at = None  # Clear to mark as sent
    if due:
        db.commit()
    return due
