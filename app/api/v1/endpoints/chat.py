
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from sqlalchemy.orm import Session
from typing import List
import uuid
import os
from pathlib import Path

from app.core.dependencies import get_db, require_permission
from app.crud import crud_chat
from app.schemas import chat as chat_schema
from app.schemas.user import User as UserSchema
from app.schemas.websockets import WebSocketMessage
from app.models.user import User
from app.core.auth import get_current_user
from app.services import team_membership_service
from app.services.connection_manager import manager
from app.core.object_storage import s3_client, BUCKET_NAME
import json

router = APIRouter()

# File upload configuration
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
ALLOWED_FILE_TYPES = {
    "image/png", "image/jpeg", "image/jpg", "image/gif", "image/webp",
    "application/pdf", "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "text/plain", "text/csv",
    "application/zip", "application/x-rar-compressed"
}

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

    messages = crud_chat.get_channel_messages(db=db, channel_id=channel_id, skip=skip, limit=limit)

    # Add reply count to each message
    for message in messages:
        message.reply_count = crud_chat.get_reply_count(db=db, message_id=message.id)

    return messages

@router.get("/messages/{message_id}/replies", response_model=List[chat_schema.InternalChatMessage], dependencies=[Depends(require_permission("chat:read"))])
def read_message_replies(
    message_id: int,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Get the parent message to check channel membership
    parent_message = crud_chat.get_message_by_id(db, message_id=message_id)
    if not parent_message:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")

    if not is_channel_member(db, user_id=current_user.id, channel_id=parent_message.channel_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You are not a member of this channel")

    replies = crud_chat.get_message_replies(db=db, message_id=message_id, skip=skip, limit=limit)

    # Add reply count to each reply (in case of nested threads)
    for reply in replies:
        reply.reply_count = crud_chat.get_reply_count(db=db, message_id=reply.id)

    return replies

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

@router.post("/upload", dependencies=[Depends(require_permission("chat:create"))])
async def upload_file(
    file: UploadFile = File(...),
    message_id: int = None,
    channel_id: int = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Upload a file to S3 and optionally attach it to a message"""

    # Validate file type
    if file.content_type not in ALLOWED_FILE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File type {file.content_type} is not allowed"
        )

    # Read file content
    content = await file.read()
    file_size = len(content)

    # Validate file size
    if file_size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File size ({file_size} bytes) exceeds maximum allowed size ({MAX_FILE_SIZE} bytes)"
        )

    # Generate unique filename
    file_extension = Path(file.filename).suffix
    unique_filename = f"chat_attachments/{uuid.uuid4()}{file_extension}"

    try:
        # Upload to S3/MinIO
        s3_client.put_object(
            Bucket=BUCKET_NAME,
            Key=unique_filename,
            Body=content,
            ContentType=file.content_type
        )

        # Generate file URL
        file_url = f"s3://{BUCKET_NAME}/{unique_filename}"

        # If message_id is provided, create attachment record
        if message_id:
            attachment_data = chat_schema.ChatAttachmentCreate(
                file_name=file.filename,
                file_url=file_url,
                file_type=file.content_type,
                file_size=file_size,
                message_id=message_id,
                uploaded_by=current_user.id
            )
            attachment = crud_chat.create_attachment(db=db, attachment=attachment_data)

            # Broadcast attachment to channel if channel_id provided
            if channel_id:
                attachment_message = WebSocketMessage(
                    type="attachment_added",
                    payload={
                        "message_id": message_id,
                        "attachment": chat_schema.ChatAttachment.from_orm(attachment).model_dump()
                    }
                )
                await manager.broadcast(attachment_message.model_dump_json(), str(channel_id))

            return {
                "file_url": file_url,
                "file_name": file.filename,
                "file_type": file.content_type,
                "file_size": file_size,
                "attachment_id": attachment.id
            }

        # Return file info without creating attachment record
        return {
            "file_url": file_url,
            "file_name": file.filename,
            "file_type": file.content_type,
            "file_size": file_size
        }

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upload file: {str(e)}"
        )

@router.get("/download/{file_key:path}", dependencies=[Depends(require_permission("chat:read"))])
async def download_file(
    file_key: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Download a file from S3"""
    try:
        # Get file from S3
        response = s3_client.get_object(Bucket=BUCKET_NAME, Key=file_key)
        content = response['Body'].read()

        # Get content type
        content_type = response.get('ContentType', 'application/octet-stream')

        # Extract filename from key
        filename = Path(file_key).name

        from fastapi.responses import Response
        return Response(
            content=content,
            media_type=content_type,
            headers={
                "Content-Disposition": f"attachment; filename={filename}"
            }
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File not found: {str(e)}"
        )

@router.post("/messages/{message_id}/reactions", response_model=chat_schema.MessageReaction, dependencies=[Depends(require_permission("chat:create"))])
async def add_message_reaction(
    message_id: int,
    emoji: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Add a reaction to a message"""
    # Verify message exists and user has access
    message = crud_chat.get_message_by_id(db, message_id=message_id)
    if not message:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")

    if not is_channel_member(db, user_id=current_user.id, channel_id=message.channel_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You are not a member of this channel")

    # Add reaction
    reaction = crud_chat.add_reaction(db=db, message_id=message_id, user_id=current_user.id, emoji=emoji)

    # Broadcast reaction via WebSocket
    reaction_message = WebSocketMessage(
        type="reaction_added",
        payload={
            "message_id": message_id,
            "reaction": chat_schema.MessageReaction.from_orm(reaction).model_dump()
        }
    )
    await manager.broadcast(reaction_message.model_dump_json(), str(message.channel_id))

    return reaction

@router.delete("/messages/{message_id}/reactions/{emoji}", dependencies=[Depends(require_permission("chat:delete"))])
async def remove_message_reaction(
    message_id: int,
    emoji: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Remove a reaction from a message"""
    # Verify message exists and user has access
    message = crud_chat.get_message_by_id(db, message_id=message_id)
    if not message:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")

    if not is_channel_member(db, user_id=current_user.id, channel_id=message.channel_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You are not a member of this channel")

    # Remove reaction
    deleted = crud_chat.remove_reaction(db=db, message_id=message_id, user_id=current_user.id, emoji=emoji)

    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reaction not found")

    # Broadcast reaction removal via WebSocket
    reaction_message = WebSocketMessage(
        type="reaction_removed",
        payload={
            "message_id": message_id,
            "user_id": current_user.id,
            "emoji": emoji
        }
    )
    await manager.broadcast(reaction_message.model_dump_json(), str(message.channel_id))

    return {"ok": True}

@router.get("/channels/{channel_id}/search", response_model=List[chat_schema.InternalChatMessage], dependencies=[Depends(require_permission("chat:read"))])
def search_channel_messages(
    channel_id: int,
    query: str,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Search messages in a channel by content"""
    if not is_channel_member(db, user_id=current_user.id, channel_id=channel_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You are not a member of this channel")

    if not query or len(query.strip()) < 2:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Search query must be at least 2 characters")

    messages = crud_chat.search_messages(db=db, channel_id=channel_id, query=query.strip(), skip=skip, limit=limit)

    # Add reply count to each message
    for message in messages:
        message.reply_count = crud_chat.get_reply_count(db=db, message_id=message.id)

    return messages
