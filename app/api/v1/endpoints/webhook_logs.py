"""
Webhook Delivery Logs API

Provides a paginated view of webhook delivery attempts for the current company.
"""
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, get_current_active_user
from app.models.user import User
from app.models.webhook_delivery_log import WebhookDeliveryLog

router = APIRouter()


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class WebhookDeliveryLogResponse(BaseModel):
    id: int
    company_id: int
    event_type: Optional[str] = None
    payload: Optional[str] = None
    webhook_url: Optional[str] = None
    status_code: Optional[int] = None
    success: bool
    error_message: Optional[str] = None
    attempt: int
    created_at: datetime

    class Config:
        from_attributes = True


class WebhookDeliveryLogListResponse(BaseModel):
    total: int
    items: List[WebhookDeliveryLogResponse]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("", response_model=WebhookDeliveryLogListResponse)
async def list_webhook_delivery_logs(
    days: int = Query(7, ge=1, le=90, description="Number of days to look back"),
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    limit: int = Query(50, ge=1, le=200, description="Items per page"),
    event_type: Optional[str] = Query(None, description="Filter by event type"),
    success: Optional[bool] = Query(None, description="Filter by delivery success status"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
    x_company_id: Optional[int] = Header(default=None),
):
    """
    Return paginated webhook delivery log entries for the current company.

    - **days**: how many days back to include (default 7, max 90)
    - **page**: page number starting at 1
    - **limit**: records per page (default 50, max 200)
    - **event_type**: optional filter, e.g. `message.delivered`
    - **success**: optional boolean filter on delivery success
    """
    # Resolve company_id — super admins may supply x_company_id header
    company_id = (
        x_company_id
        if current_user.is_super_admin and x_company_id
        else current_user.company_id
    )

    cutoff = datetime.utcnow() - timedelta(days=days)
    offset = (page - 1) * limit

    query = db.query(WebhookDeliveryLog).filter(
        WebhookDeliveryLog.company_id == company_id,
        WebhookDeliveryLog.created_at >= cutoff,
    )

    if event_type is not None:
        query = query.filter(WebhookDeliveryLog.event_type == event_type)

    if success is not None:
        query = query.filter(WebhookDeliveryLog.success == success)

    total = query.count()

    items = (
        query
        .order_by(WebhookDeliveryLog.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    return WebhookDeliveryLogListResponse(
        total=total,
        items=[WebhookDeliveryLogResponse.model_validate(item) for item in items],
    )
