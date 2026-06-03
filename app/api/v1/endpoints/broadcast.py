"""
Broadcast endpoints

POST /broadcasts              — create broadcast
GET  /broadcasts              — list broadcasts
GET  /broadcasts/{id}         — get broadcast (with live stats)
POST /broadcasts/{id}/send    — trigger send (fire-and-forget)
DELETE /broadcasts/{id}       — delete (only if not running)
GET  /broadcasts/{id}/contacts — per-contact delivery status
"""
import logging
import asyncio
from datetime import datetime
from typing import Optional, List, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, get_current_active_user
from app.models.user import User
from app.services import broadcast_service

router = APIRouter()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class BroadcastCreate(BaseModel):
    name: str
    channel: Literal["whatsapp", "sms", "email"]
    message: str
    subject: Optional[str] = None
    segment_id: Optional[int] = None
    scheduled_at: Optional[datetime] = None


class BroadcastResponse(BaseModel):
    id: int
    name: str
    channel: str
    message: str
    subject: Optional[str]
    segment_id: Optional[int]
    status: str
    total_contacts: int
    sent_count: int
    failed_count: int
    skipped_count: int
    scheduled_at: Optional[datetime]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    created_at: datetime


class BroadcastContactResponse(BaseModel):
    contact_id: int
    contact_name: Optional[str]
    contact_phone: Optional[str]
    status: str
    error_message: Optional[str]
    sent_at: Optional[datetime]


def _to_response(b) -> BroadcastResponse:
    return BroadcastResponse(
        id=b.id, name=b.name, channel=b.channel.value, message=b.message,
        subject=b.subject,
        segment_id=b.segment_id, status=b.status.value,
        total_contacts=b.total_contacts or 0,
        sent_count=b.sent_count or 0,
        failed_count=b.failed_count or 0,
        skipped_count=b.skipped_count or 0,
        scheduled_at=b.scheduled_at, started_at=b.started_at,
        completed_at=b.completed_at, created_at=b.created_at,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("", response_model=BroadcastResponse, status_code=201)
def create_broadcast(
    body: BroadcastCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
    x_company_id: int = Header(...),
):
    broadcast = broadcast_service.create_broadcast(
        db=db,
        company_id=x_company_id,
        name=body.name,
        channel=body.channel,
        message=body.message,
        subject=body.subject,
        segment_id=body.segment_id,
        scheduled_at=body.scheduled_at,
        created_by_user_id=current_user.id,
    )
    return _to_response(broadcast)


@router.get("", response_model=List[BroadcastResponse])
def list_broadcasts(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
    x_company_id: int = Header(...),
):
    return [_to_response(b) for b in broadcast_service.list_broadcasts(db, x_company_id)]


@router.get("/{broadcast_id}", response_model=BroadcastResponse)
def get_broadcast(
    broadcast_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
    x_company_id: int = Header(...),
):
    b = broadcast_service.get_broadcast(db, broadcast_id, x_company_id)
    if not b:
        raise HTTPException(status_code=404, detail="Broadcast not found.")
    return _to_response(b)


@router.post("/{broadcast_id}/send", response_model=BroadcastResponse)
async def send_broadcast(
    broadcast_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
    x_company_id: int = Header(...),
):
    """Trigger broadcast send — runs in background, returns immediately."""
    b = broadcast_service.get_broadcast(db, broadcast_id, x_company_id)
    if not b:
        raise HTTPException(status_code=404, detail="Broadcast not found.")
    if b.status.value == "running":
        raise HTTPException(status_code=409, detail="Broadcast is already running.")
    if b.status.value == "completed":
        raise HTTPException(status_code=409, detail="Broadcast already completed.")

    background_tasks.add_task(broadcast_service.send_broadcast, db, broadcast_id, x_company_id)
    return _to_response(b)


@router.delete("/{broadcast_id}", status_code=204)
def delete_broadcast(
    broadcast_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
    x_company_id: int = Header(...),
):
    deleted = broadcast_service.delete_broadcast(db, broadcast_id, x_company_id)
    if not deleted:
        raise HTTPException(status_code=400, detail="Cannot delete — not found or currently running.")


@router.get("/{broadcast_id}/contacts", response_model=List[BroadcastContactResponse])
def get_broadcast_contacts(
    broadcast_id: int,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
    x_company_id: int = Header(...),
):
    b = broadcast_service.get_broadcast(db, broadcast_id, x_company_id)
    if not b:
        raise HTTPException(status_code=404, detail="Broadcast not found.")
    rows = broadcast_service.get_broadcast_contacts(db, broadcast_id, x_company_id, limit, offset)
    return [
        BroadcastContactResponse(
            contact_id=r.contact_id,
            contact_name=r.contact.name if r.contact else None,
            contact_phone=r.contact.phone_number if r.contact else None,
            status=r.status.value,
            error_message=r.error_message,
            sent_at=r.sent_at,
        )
        for r in rows
    ]
