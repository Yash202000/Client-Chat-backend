
from pydantic import BaseModel
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
    channel_id: int

# Schemas for creating new objects
class ChannelMembershipCreate(ChannelMembershipBase):
    pass

class ChatChannelCreate(ChatChannelBase):
    pass

class InternalChatMessageCreate(InternalChatMessageBase):
    pass

# Schemas for reading/returning objects from the API
class UserInChat(BaseModel):
    id: int
    email: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    presence_status: str

    class Config:
        orm_mode = True

class ChannelMembership(ChannelMembershipBase):
    id: int
    joined_at: datetime.datetime

    class Config:
        orm_mode = True

class InternalChatMessage(InternalChatMessageBase):
    id: int
    sender_id: int
    created_at: datetime.datetime
    sender: UserInChat

    class Config:
        orm_mode = True

class ChatChannel(ChatChannelBase):
    id: int
    creator_id: Optional[int] = None
    created_at: datetime.datetime
    participants: List[ChannelMembership] = []
    messages: List[InternalChatMessage] = []

    class Config:
        orm_mode = True
