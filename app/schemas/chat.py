
from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing import Any, List, Optional
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
    scheduled_at: Optional[datetime.datetime] = None
    is_activity: Optional[bool] = False

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
    member_ids: Optional[List[int]] = []

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

class ChannelMembershipUser(BaseModel):
    id: int
    email: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    profile_picture_url: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)

class ChannelMembership(ChannelMembershipBase):
    id: int
    joined_at: datetime.datetime
    user: Optional[ChannelMembershipUser] = None

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
    reply_count: Optional[int] = 0
    read_by: Optional[List['MessageReadUser']] = []
    # Read from ORM but excluded from the JSON response
    extra_data: Optional[dict] = Field(default=None, exclude=True)

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode='after')
    def populate_is_activity(self) -> 'InternalChatMessage':
        if self.extra_data and self.extra_data.get('is_activity'):
            self.is_activity = True
        return self

class ChatChannel(ChatChannelBase):
    id: int
    creator_id: Optional[int] = None
    created_at: datetime.datetime
    participants: List[ChannelMembership] = []
    messages: List[InternalChatMessage] = []

    model_config = ConfigDict(from_attributes=True)


# ── New feature schemas ────────────────────────────────────────────────────────

class MessageReadUser(BaseModel):
    id: int
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: str
    profile_picture_url: Optional[str] = None
    read_at: datetime.datetime

    model_config = ConfigDict(from_attributes=True)


class PinnedMessageOut(BaseModel):
    id: int
    channel_id: int
    message_id: int
    pinned_by_user_id: int
    pinned_at: datetime.datetime
    message: InternalChatMessage
    pinned_by: UserInChat

    model_config = ConfigDict(from_attributes=True)


class UserStatusUpdate(BaseModel):
    presence_status: Optional[str] = None  # online, offline, busy, dnd
    status_message: Optional[str] = None
    dnd_minutes: Optional[int] = None  # If set, dnd_until = now + dnd_minutes


class UserStatusOut(BaseModel):
    id: int
    presence_status: str
    status_message: Optional[str] = None
    dnd_until: Optional[datetime.datetime] = None

    model_config = ConfigDict(from_attributes=True)
