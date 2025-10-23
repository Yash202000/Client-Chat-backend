
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app.core.dependencies import get_db, require_permission
from app.crud import crud_chat
from app.schemas import chat as chat_schema
from app.schemas.user import User as UserSchema
from app.schemas.websockets import WebSocketMessage
from app.models.user import User
from app.core.auth import get_current_user
from app.services import team_membership_service
from app.services.connection_manager import manager
import json

router = APIRouter()

def is_channel_member(db: Session, user_id: int, channel_id: int) -> bool:
    members = crud_chat.get_channel_members(db, channel_id=channel_id)
    return any(member.id == user_id for member in members)

@router.post("/channels/", response_model=chat_schema.ChatChannel, dependencies=[Depends(require_permission("chat:create"))])
def create_channel(
    channel: chat_schema.ChatChannelCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if channel.team_id:
        is_member = team_membership_service.is_user_in_team(db, user_id=current_user.id, team_id=channel.team_id)
        if not is_member:
            raise HTTPException(status_code=403, detail="You are not a member of this team")
    return crud_chat.create_channel(db=db, channel=channel, creator_id=current_user.id, company_id=current_user.company_id)

@router.get("/channels/", response_model=List[chat_schema.ChatChannel], dependencies=[Depends(require_permission("chat:read"))])
def read_user_channels(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return crud_chat.get_user_channels(db=db, user_id=current_user.id)

@router.get("/channels/{channel_id}/messages", response_model=List[chat_schema.InternalChatMessage], dependencies=[Depends(require_permission("chat:read"))])
def read_channel_messages(
    channel_id: int,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not is_channel_member(db, user_id=current_user.id, channel_id=channel_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You are not a member of this channel")
    return crud_chat.get_channel_messages(db=db, channel_id=channel_id, skip=skip, limit=limit)

@router.post("/channels/{channel_id}/messages", response_model=chat_schema.InternalChatMessage, dependencies=[Depends(require_permission("chat:create"))])
async def create_message(
    channel_id: int,
    message: chat_schema.InternalChatMessageCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not is_channel_member(db, user_id=current_user.id, channel_id=channel_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You are not a member of this channel")
    message.channel_id = channel_id
    new_message = crud_chat.create_message(db=db, message=message, sender_id=current_user.id)
    
    message_data = chat_schema.InternalChatMessage.from_orm(new_message)
    websocket_message = WebSocketMessage(type="new_message", payload=message_data.model_dump())
    
    print(f"Broadcasting message: {websocket_message.model_dump_json()}")
    # Broadcast the new message to all connected clients in the channel
    await manager.broadcast(websocket_message.model_dump_json(), str(channel_id))
    print(f"Finished broadcasting to channel {channel_id}")
    
    return new_message

@router.post("/channels/{channel_id}/join", response_model=chat_schema.ChannelMembership, dependencies=[Depends(require_permission("chat:update"))])
def join_channel(
    channel_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return crud_chat.add_user_to_channel(db=db, user_id=current_user.id, channel_id=channel_id)

@router.post("/channels/{channel_id}/leave", dependencies=[Depends(require_permission("chat:update"))])
def leave_channel(
    channel_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    crud_chat.remove_user_from_channel(db=db, user_id=current_user.id, channel_id=channel_id)
    return {"ok": True}

@router.get("/channels/{channel_id}/members", response_model=List[UserSchema], dependencies=[Depends(require_permission("chat:read"))])
def get_channel_members(
    channel_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not is_channel_member(db, user_id=current_user.id, channel_id=channel_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You are not a member of this channel")
    return crud_chat.get_channel_members(db=db, channel_id=channel_id)

class ChannelMemberCreate(chat_schema.BaseModel):
    user_id: int

@router.post("/channels/{channel_id}/members", response_model=chat_schema.ChannelMembership, dependencies=[Depends(require_permission("chat:update"))])
def add_channel_member(
    channel_id: int,
    member: ChannelMemberCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # TODO: Add validation to ensure only admins or channel creators can add members
    return crud_chat.add_user_to_channel(db=db, user_id=member.user_id, channel_id=channel_id)

@router.delete("/channels/{channel_id}/members/{user_id}", dependencies=[Depends(require_permission("chat:delete"))])
def remove_channel_member(
    channel_id: int,
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # TODO: Add validation to ensure only admins or channel creators can remove members
    crud_chat.remove_user_from_channel(db=db, user_id=user_id, channel_id=channel_id)
    return {"ok": True}
