
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import List
import uuid
import os
import datetime
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

class ChannelRename(chat_schema.BaseModel):
    name: str

@router.patch("/channels/{channel_id}", response_model=chat_schema.ChatChannel, dependencies=[Depends(require_permission("chat:update"))])
def rename_channel(
    channel_id: int,
    body: ChannelRename,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not is_channel_member(db, user_id=current_user.id, channel_id=channel_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You are not a member of this channel")
    channel = crud_chat.rename_channel(db=db, channel_id=channel_id, name=body.name)
    if not channel:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Channel not found")
    return channel

@router.get("/channels/", response_model=List[chat_schema.ChatChannel], dependencies=[Depends(require_permission("chat:read"))])
def read_user_channels(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return crud_chat.get_user_channels(db=db, user_id=current_user.id)


@router.get("/channels/summary", dependencies=[Depends(require_permission("chat:read"))])
def get_channels_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Returns channels with last_message preview and unread_count, sorted by activity."""
    rows = crud_chat.get_user_channels_with_summary(db=db, user_id=current_user.id)
    result = []
    for row in rows:
        ch = row["channel"]
        result.append({
            "id": ch.id,
            "name": ch.name,
            "description": ch.description,
            "channel_type": ch.channel_type,
            "team_id": ch.team_id,
            "creator_id": ch.creator_id,
            "created_at": ch.created_at.isoformat(),
            "participants": [
                {
                    "id": m.id,
                    "user_id": m.user_id,
                    "channel_id": m.channel_id,
                    "joined_at": m.joined_at.isoformat() if m.joined_at else None,
                    "user": {
                        "id": m.user.id,
                        "email": m.user.email,
                        "first_name": m.user.first_name,
                        "last_name": m.user.last_name,
                        "profile_picture_url": m.user.profile_picture_url,
                    } if m.user else None,
                }
                for m in ch.participants
            ],
            "last_message": row["last_message"],
            "unread_count": row["unread_count"],
        })
    return result

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

    # Broadcast to channel WebSocket (for members currently on that channel)
    await manager.broadcast(websocket_message.model_dump_json(), str(channel_id))

    # Broadcast to company WebSocket so users on other pages get a toast notification
    channel = crud_chat.get_channel(db, channel_id=channel_id)
    channel_members = crud_chat.get_channel_members(db, channel_id=channel_id)
    channel_member_ids = [m.id for m in channel_members]
    company_msg = json.loads(websocket_message.model_dump_json())
    company_msg['payload']['channel_member_ids'] = channel_member_ids
    company_msg['payload']['channel_name'] = channel.name if channel else None
    await manager.broadcast(json.dumps(company_msg), str(current_user.company_id))

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
    channel = crud_chat.get_channel(db, channel_id=channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    if channel.creator_id != current_user.id and not current_user.is_super_admin:
        raise HTTPException(status_code=403, detail="Only the channel creator or an admin can add members")
    return crud_chat.add_user_to_channel(db=db, user_id=member.user_id, channel_id=channel_id)

@router.delete("/channels/{channel_id}/members/{user_id}", dependencies=[Depends(require_permission("chat:delete"))])
def remove_channel_member(
    channel_id: int,
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    channel = crud_chat.get_channel(db, channel_id=channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    if channel.creator_id != current_user.id and not current_user.is_super_admin:
        raise HTTPException(status_code=403, detail="Only the channel creator or an admin can remove members")
    crud_chat.remove_user_from_channel(db=db, user_id=user_id, channel_id=channel_id)
    return {"ok": True}

@router.post("/upload", dependencies=[Depends(require_permission("chat:create"))])
async def upload_file(
    file: UploadFile = File(...),
    message_id: int = Form(None),
    channel_id: int = Form(None),
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
                attachment_payload = chat_schema.ChatAttachment.from_orm(attachment).model_dump()
                attachment_message = WebSocketMessage(
                    type="attachment_added",
                    payload={
                        "message_id": message_id,
                        "channel_id": channel_id,
                        "attachment": attachment_payload,
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
    inline: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Download or inline-preview a file from S3"""
    try:
        response = s3_client.get_object(Bucket=BUCKET_NAME, Key=file_key)
        content = response['Body'].read()
        content_type = response.get('ContentType', 'application/octet-stream')
        filename = Path(file_key).name
        disposition = f"inline; filename=\"{filename}\"" if inline else f"attachment; filename=\"{filename}\""
        from fastapi.responses import Response
        return Response(
            content=content,
            media_type=content_type,
            headers={"Content-Disposition": disposition},
        )
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"File not found: {str(e)}")

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


# ── Global cross-channel search ───────────────────────────────────────────────

@router.get("/search", dependencies=[Depends(require_permission("chat:read"))])
def search_all_channels(
    query: str,
    limit: int = 30,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Search messages across all channels the current user is a member of."""
    from app.models.chat_channel import ChatChannel as ChatChannelModel
    from app.models.channel_membership import ChannelMembership

    if not query or len(query.strip()) < 2:
        raise HTTPException(status_code=400, detail="Query must be at least 2 characters")

    member_channel_ids = (
        db.query(ChannelMembership.channel_id)
        .filter(ChannelMembership.user_id == current_user.id)
        .subquery()
    )

    from app.models.internal_chat_message import InternalChatMessage as MsgModel
    rows = (
        db.query(MsgModel)
        .filter(
            MsgModel.channel_id.in_(member_channel_ids),
            MsgModel.content.ilike(f"%{query.strip()}%"),
        )
        .order_by(MsgModel.created_at.desc())
        .limit(limit)
        .all()
    )

    channel_ids = list({r.channel_id for r in rows})
    channels = {
        c.id: c
        for c in db.query(ChatChannelModel).filter(ChatChannelModel.id.in_(channel_ids)).all()
    }

    results = []
    for msg in rows:
        ch = channels.get(msg.channel_id)
        msg.reply_count = crud_chat.get_reply_count(db=db, message_id=msg.id)
        d = chat_schema.InternalChatMessage.from_orm(msg).model_dump()
        d["channel_name"] = ch.name if ch else None
        d["channel_type"] = ch.channel_type if ch else None
        results.append(d)

    return results


# ── Drive file sharing ─────────────────────────────────────────────────────────

class ShareDriveFileBody(BaseModel):
    drive_item_id: int
    content: str = ""

@router.post("/channels/{channel_id}/share-drive-file", dependencies=[Depends(require_permission("chat:create"))])
async def share_drive_file(
    channel_id: int,
    body: ShareDriveFileBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Attach a Drive file to a new message without re-uploading it."""
    from app.models.drive_item import DriveItem

    if not is_channel_member(db, user_id=current_user.id, channel_id=channel_id):
        raise HTTPException(status_code=403, detail="Not a channel member")

    item = db.query(DriveItem).filter(
        DriveItem.id == body.drive_item_id,
        DriveItem.company_id == current_user.company_id,
        DriveItem.is_folder == False,
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Drive file not found")

    # Generate a 1-hour presigned URL
    download_url = s3_client.generate_presigned_url(
        "get_object",
        Params={"Bucket": BUCKET_NAME, "Key": item.s3_key},
        ExpiresIn=3600,
    )

    # Create the message
    from app.schemas.chat import InternalChatMessageCreate
    msg = crud_chat.create_message(
        db=db,
        message=InternalChatMessageCreate(channel_id=channel_id, content=body.content or ""),
        sender_id=current_user.id,
    )

    # Create the attachment record
    attachment = crud_chat.create_attachment(db=db, attachment=chat_schema.ChatAttachmentCreate(
        file_name=item.name,
        file_url=download_url,
        file_type=item.mime_type or "application/octet-stream",
        file_size=item.file_size or 0,
        message_id=msg.id,
        uploaded_by=current_user.id,
    ))

    # Reload message so attachments are included
    db.refresh(msg)
    message_data = chat_schema.InternalChatMessage.from_orm(msg)
    await manager.broadcast(
        WebSocketMessage(type="new_message", payload=message_data.model_dump()).model_dump_json(),
        str(channel_id),
    )
    return message_data


# ── Pinned Messages ────────────────────────────────────────────────────────────

@router.post("/channels/{channel_id}/pins", response_model=chat_schema.PinnedMessageOut, dependencies=[Depends(require_permission("chat:create"))])
async def pin_message(
    channel_id: int,
    message_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not is_channel_member(db, user_id=current_user.id, channel_id=channel_id):
        raise HTTPException(status_code=403, detail="Not a channel member")
    message = crud_chat.get_message_by_id(db, message_id)
    if not message or message.channel_id != channel_id:
        raise HTTPException(status_code=404, detail="Message not found in this channel")
    pin = crud_chat.pin_message(db, channel_id=channel_id, message_id=message_id, user_id=current_user.id)
    ws_msg = WebSocketMessage(type="message_pinned", payload={"channel_id": channel_id, "message_id": message_id, "pinned_by": current_user.id})
    await manager.broadcast(ws_msg.model_dump_json(), str(channel_id))
    return pin


@router.delete("/channels/{channel_id}/pins/{message_id}", dependencies=[Depends(require_permission("chat:delete"))])
async def unpin_message(
    channel_id: int,
    message_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not is_channel_member(db, user_id=current_user.id, channel_id=channel_id):
        raise HTTPException(status_code=403, detail="Not a channel member")
    deleted = crud_chat.unpin_message(db, channel_id=channel_id, message_id=message_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Pin not found")
    ws_msg = WebSocketMessage(type="message_unpinned", payload={"channel_id": channel_id, "message_id": message_id})
    await manager.broadcast(ws_msg.model_dump_json(), str(channel_id))
    return {"ok": True}


@router.get("/channels/{channel_id}/pins", response_model=List[chat_schema.PinnedMessageOut], dependencies=[Depends(require_permission("chat:read"))])
def get_pinned_messages(
    channel_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not is_channel_member(db, user_id=current_user.id, channel_id=channel_id):
        raise HTTPException(status_code=403, detail="Not a channel member")
    pins = crud_chat.get_pinned_messages(db, channel_id=channel_id)
    for pin in pins:
        if pin.message:
            pin.message.reply_count = crud_chat.get_reply_count(db, message_id=pin.message_id)
    return pins


# ── Read Receipts ──────────────────────────────────────────────────────────────

@router.post("/channels/{channel_id}/read", dependencies=[Depends(require_permission("chat:create"))])
async def mark_channel_read(
    channel_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not is_channel_member(db, user_id=current_user.id, channel_id=channel_id):
        raise HTTPException(status_code=403, detail="Not a channel member")
    crud_chat.mark_channel_read(db, channel_id=channel_id, user_id=current_user.id)
    # Broadcast so the sender's UI updates the double tick immediately
    ws_msg = WebSocketMessage(
        type="channel_read",
        payload={"channel_id": channel_id, "user_id": current_user.id}
    )
    await manager.broadcast(ws_msg.model_dump_json(), str(channel_id))
    return {"ok": True}


@router.get("/channels/{channel_id}/read-summary", dependencies=[Depends(require_permission("chat:read"))])
def get_channel_read_summary(
    channel_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Returns {message_id: [{id, first_name, last_name, email, profile_picture_url}]} for all read messages in channel."""
    if not is_channel_member(db, user_id=current_user.id, channel_id=channel_id):
        raise HTTPException(status_code=403, detail="Not a channel member")
    read_map = crud_chat.get_channel_read_map(db, channel_id=channel_id)
    result = {}
    for message_id, reads in read_map.items():
        result[str(message_id)] = [
            {
                "id": r.user.id,
                "first_name": r.user.first_name,
                "last_name": r.user.last_name,
                "email": r.user.email,
                "profile_picture_url": r.user.profile_picture_url,
            }
            for r in reads
            if r.user_id != current_user.id  # Don't show yourself as a reader
        ]
    return result


@router.post("/messages/{message_id}/read", dependencies=[Depends(require_permission("chat:create"))])
def mark_message_read(
    message_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    message = crud_chat.get_message_by_id(db, message_id)
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")
    if not is_channel_member(db, user_id=current_user.id, channel_id=message.channel_id):
        raise HTTPException(status_code=403, detail="Not a channel member")
    crud_chat.mark_message_read(db, message_id=message_id, user_id=current_user.id)
    return {"ok": True}


# ── Scheduled Messages ─────────────────────────────────────────────────────────

@router.get("/scheduled", response_model=List[chat_schema.InternalChatMessage], dependencies=[Depends(require_permission("chat:read"))])
def get_my_scheduled_messages(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    messages = crud_chat.get_scheduled_messages(db, user_id=current_user.id)
    for m in messages:
        m.reply_count = 0
    return messages


@router.delete("/scheduled/{message_id}", dependencies=[Depends(require_permission("chat:delete"))])
def cancel_scheduled_message(
    message_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    message = crud_chat.get_message_by_id(db, message_id)
    if not message or message.sender_id != current_user.id:
        raise HTTPException(status_code=404, detail="Scheduled message not found")
    if not message.scheduled_at:
        raise HTTPException(status_code=400, detail="Message is not scheduled")
    db.delete(message)
    db.commit()
    return {"ok": True}


# ── User Status / DND ──────────────────────────────────────────────────────────

@router.patch("/status", response_model=chat_schema.UserStatusOut, dependencies=[Depends(require_permission("chat:update"))])
def update_user_status(
    body: chat_schema.UserStatusUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if body.presence_status:
        current_user.presence_status = body.presence_status
    if body.status_message is not None:
        current_user.status_message = body.status_message
    if body.dnd_minutes is not None and body.dnd_minutes > 0:
        current_user.dnd_until = datetime.datetime.utcnow() + datetime.timedelta(minutes=body.dnd_minutes)
        current_user.presence_status = "dnd"
    elif body.dnd_minutes == 0:
        current_user.dnd_until = None
    db.commit()
    db.refresh(current_user)
    return current_user
