
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.core.dependencies import get_db
from app.crud import crud_chat
from app.schemas import chat as chat_schema
from app.models import User
from app.core.auth import get_current_user
from app.api.v1.endpoints.websockets import manager
import json

router = APIRouter()

@router.post("/channels/", response_model=chat_schema.ChatChannel)
def create_channel(
    channel: chat_schema.ChatChannelCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # TODO: Add validation to ensure user is part of the team if it's a team channel
    return crud_chat.create_channel(db=db, channel=channel, creator_id=current_user.id, company_id=current_user.company_id)

@router.get("/channels/", response_model=List[chat_schema.ChatChannel])
def read_user_channels(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return crud_chat.get_user_channels(db=db, user_id=current_user.id)

@router.get("/channels/{channel_id}/messages", response_model=List[chat_schema.InternalChatMessage])
def read_channel_messages(
    channel_id: int,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # TODO: Add validation to ensure user is a member of the channel
    return crud_chat.get_channel_messages(db=db, channel_id=channel_id, skip=skip, limit=limit)

@router.post("/channels/{channel_id}/messages", response_model=chat_schema.InternalChatMessage)
async def create_message(
    channel_id: int,
    message: chat_schema.InternalChatMessageCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # TODO: Add validation to ensure user is a member of the channel
    message.channel_id = channel_id
    new_message = crud_chat.create_message(db=db, message=message, sender_id=current_user.id)
    
    # Broadcast the new message to all connected clients in the channel
    await manager.broadcast(json.dumps(chat_schema.InternalChatMessage.from_orm(new_message).dict()), channel_id)
    
    return new_message

@router.post("/channels/{channel_id}/join", response_model=chat_schema.ChannelMembership)
def join_channel(
    channel_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return crud_chat.add_user_to_channel(db=db, user_id=current_user.id, channel_id=channel_id)

@router.post("/channels/{channel_id}/leave")
def leave_channel(
    channel_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    crud_chat.remove_user_from_channel(db=db, user_id=current_user.id, channel_id=channel_id)
    return {"ok": True}
