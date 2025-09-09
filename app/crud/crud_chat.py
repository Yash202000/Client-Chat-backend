
from sqlalchemy.orm import Session
from app.models import ChatChannel, ChannelMembership, InternalChatMessage, User, Team
from app.schemas import chat as chat_schema
from typing import List, Optional

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

# CRUD for InternalChatMessage
def create_message(db: Session, message: chat_schema.InternalChatMessageCreate, sender_id: int) -> InternalChatMessage:
    db_message = InternalChatMessage(content=message.content, channel_id=message.channel_id, sender_id=sender_id)
    db.add(db_message)
    db.commit()
    db.refresh(db_message)
    return db_message

def get_channel_messages(db: Session, channel_id: int, skip: int = 0, limit: int = 100) -> List[InternalChatMessage]:
    return db.query(InternalChatMessage).filter(InternalChatMessage.channel_id == channel_id).order_by(InternalChatMessage.created_at.asc()).offset(skip).limit(limit).all()
