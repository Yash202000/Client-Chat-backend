from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app.core.dependencies import get_db, require_permission
from app.crud import crud_notification
from app.schemas import notification as notification_schema
from app.models.user import User
from app.core.auth import get_current_user
from app.schemas.websockets import WebSocketMessage
from app.services.connection_manager import manager

router = APIRouter()

@router.get("/", response_model=List[notification_schema.Notification], dependencies=[Depends(require_permission("chat:read"))])
def get_notifications(
    skip: int = 0,
    limit: int = 50,
    unread_only: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get notifications for the current user"""
    return crud_notification.get_user_notifications(
        db=db,
        user_id=current_user.id,
        skip=skip,
        limit=limit,
        unread_only=unread_only
    )

@router.get("/unread-count", response_model=notification_schema.NotificationCount, dependencies=[Depends(require_permission("chat:read"))])
def get_unread_count(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get count of unread notifications"""
    count = crud_notification.get_unread_count(db=db, user_id=current_user.id)
    return {"unread_count": count}

@router.patch("/{notification_id}/read", dependencies=[Depends(require_permission("chat:update"))])
def mark_notification_read(
    notification_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Mark a notification as read"""
    success = crud_notification.mark_notification_as_read(
        db=db,
        notification_id=notification_id,
        user_id=current_user.id
    )
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found"
        )
    return {"ok": True}

@router.patch("/mark-all-read", dependencies=[Depends(require_permission("chat:update"))])
def mark_all_notifications_read(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Mark all notifications as read"""
    count = crud_notification.mark_all_as_read(db=db, user_id=current_user.id)
    return {"updated_count": count}

@router.delete("/{notification_id}", dependencies=[Depends(require_permission("chat:delete"))])
def delete_notification(
    notification_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a notification"""
    success = crud_notification.delete_notification(
        db=db,
        notification_id=notification_id,
        user_id=current_user.id
    )
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found"
        )
    return {"ok": True}
