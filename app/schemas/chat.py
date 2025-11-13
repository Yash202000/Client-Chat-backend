
from pydantic import BaseModel, ConfigDict
from typing import List, Optional
import datetime

# Base schemas
class ChannelMembershipBase(BaseModel):
    user_id: int
    channel_id: int

class ChatChannelBase(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    channel_type: str
    team_id: Optional[int] = None

class InternalChatMessageBase(BaseModel):
    content: str
    channel_id: Optional[int] = None
    parent_message_id: Optional[int] = None  # For threading

    model_config = ConfigDict(from_attributes=True)

class ChatAttachmentBase(BaseModel):
    file_name: str
    file_url: str
    file_type: str
    file_size: int

# Schemas for creating new objects
class ChannelMembershipCreate(ChannelMembershipBase):
    pass

class ChatChannelCreate(ChatChannelBase):
    pass

class InternalChatMessageCreate(InternalChatMessageBase):
    pass

class ChatAttachmentCreate(ChatAttachmentBase):
    message_id: int
    uploaded_by: int

class MessageReactionBase(BaseModel):
    emoji: str

class MessageReactionCreate(MessageReactionBase):
    message_id: int

class MessageReaction(MessageReactionBase):
    id: int
    message_id: int
    user_id: int
    created_at: datetime.datetime

    model_config = ConfigDict(from_attributes=True)

# Schemas for reading/returning objects from the API
class UserInChat(BaseModel):
    id: int
    email: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    presence_status: str

    model_config = ConfigDict(from_attributes=True)

class ChannelMembership(ChannelMembershipBase):
    id: int
    joined_at: datetime.datetime

    model_config = ConfigDict(from_attributes=True)

class ChatAttachment(ChatAttachmentBase):
    id: int
    message_id: int
    uploaded_by: int
    created_at: datetime.datetime

    model_config = ConfigDict(from_attributes=True)

class InternalChatMessage(InternalChatMessageBase):
    id: int
    sender_id: int
    created_at: datetime.datetime
    sender: UserInChat
    attachments: List[ChatAttachment] = []
    reactions: List['MessageReaction'] = []
    reply_count: Optional[int] = 0  # Computed field for number of replies

    model_config = ConfigDict(from_attributes=True)

class ChatChannel(ChatChannelBase):
    id: int
    creator_id: Optional[int] = None
    created_at: datetime.datetime
    participants: List[ChannelMembership] = []
    messages: List[InternalChatMessage] = []

    model_config = ConfigDict(from_attributes=True)
