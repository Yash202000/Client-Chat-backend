"""
Click to Social (CTS) endpoints

Protected:
  POST   /cts              — create link
  GET    /cts?channel=     — list links (optional channel filter)
  GET    /cts/{id}         — get link
  PUT    /cts/{id}         — update link
  DELETE /cts/{id}         — delete link
  GET    /cts/{id}/clicks  — click log

Public (no auth):
  GET    /public/cts/{key} — record click + redirect to channel deep link
"""
import logging
from typing import Optional, List
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, get_current_active_user
from app.core.config import settings
from app.models.user import User
from app.services import cts_service

router = APIRouter()
public_router = APIRouter()
logger = logging.getLogger(__name__)

VALID_CHANNELS = {"whatsapp", "instagram", "telegram", "messenger"}


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class LinkCreate(BaseModel):
    channel: str
    name: str
    handle: str
    prefill_message: Optional[str] = None
    utm_source: Optional[str] = None
    utm_medium: Optional[str] = None
    utm_campaign: Optional[str] = None
    utm_content: Optional[str] = None
    auto_tag: Optional[str] = None
    workflow_id: Optional[int] = None


class LinkUpdate(BaseModel):
    name: Optional[str] = None
    handle: Optional[str] = None
    prefill_message: Optional[str] = None
    utm_source: Optional[str] = None
    utm_medium: Optional[str] = None
    utm_campaign: Optional[str] = None
    utm_content: Optional[str] = None
    auto_tag: Optional[str] = None
    workflow_id: Optional[int] = None
    is_active: Optional[bool] = None


class LinkResponse(BaseModel):
    id: int
    link_key: str
    channel: str
    name: str
    handle: str
    prefill_message: Optional[str]
    utm_source: Optional[str]
    utm_medium: Optional[str]
    utm_campaign: Optional[str]
    utm_content: Optional[str]
    auto_tag: Optional[str]
    workflow_id: Optional[int]
    click_count: int
    contact_count: int
    is_active: bool
    created_at: datetime
    short_url: str
    channel_url: str


class ClickResponse(BaseModel):
    id: int
    referrer_url: Optional[str]
    contact_id: Optional[int]
    clicked_at: datetime
    converted_at: Optional[datetime]


def _to_response(link) -> LinkResponse:
    backend_url = settings.BACKEND_URL if hasattr(settings, "BACKEND_URL") else ""
    return LinkResponse(
        id=link.id,
        link_key=link.link_key,
        channel=link.channel,
        name=link.name,
        handle=link.handle,
        prefill_message=link.prefill_message,
        utm_source=link.utm_source,
        utm_medium=link.utm_medium,
        utm_campaign=link.utm_campaign,
        utm_content=link.utm_content,
        auto_tag=link.auto_tag,
        workflow_id=link.workflow_id,
        click_count=link.click_count or 0,
        contact_count=link.contact_count or 0,
        is_active=link.is_active,
        created_at=link.created_at,
        short_url=cts_service.build_short_url(link, backend_url),
        channel_url=cts_service.build_channel_url(link),
    )


# ---------------------------------------------------------------------------
# Protected routes
# ---------------------------------------------------------------------------

@router.post("", response_model=LinkResponse, status_code=201)
def create_link(
    body: LinkCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
    x_company_id: int = Header(...),
):
    if body.channel not in VALID_CHANNELS:
        raise HTTPException(status_code=400, detail=f"Invalid channel. Must be one of: {', '.join(VALID_CHANNELS)}")
    link = cts_service.create_link(db, company_id=x_company_id, **body.model_dump())
    return _to_response(link)


@router.get("", response_model=List[LinkResponse])
def list_links(
    channel: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
    x_company_id: int = Header(...),
):
    return [_to_response(l) for l in cts_service.list_links(db, x_company_id, channel=channel)]


@router.get("/{link_id}", response_model=LinkResponse)
def get_link(
    link_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
    x_company_id: int = Header(...),
):
    link = cts_service.get_link(db, link_id, x_company_id)
    if not link:
        raise HTTPException(status_code=404, detail="Link not found.")
    return _to_response(link)


@router.put("/{link_id}", response_model=LinkResponse)
def update_link(
    link_id: int,
    body: LinkUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
    x_company_id: int = Header(...),
):
    link = cts_service.update_link(db, link_id, x_company_id, **body.model_dump(exclude_none=True))
    if not link:
        raise HTTPException(status_code=404, detail="Link not found.")
    return _to_response(link)


@router.delete("/{link_id}", status_code=204)
def delete_link(
    link_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
    x_company_id: int = Header(...),
):
    if not cts_service.delete_link(db, link_id, x_company_id):
        raise HTTPException(status_code=404, detail="Link not found.")


@router.get("/{link_id}/clicks", response_model=List[ClickResponse])
def get_clicks(
    link_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
    x_company_id: int = Header(...),
):
    link = cts_service.get_link(db, link_id, x_company_id)
    if not link:
        raise HTTPException(status_code=404, detail="Link not found.")
    clicks = cts_service.list_clicks(db, link_id, x_company_id)
    return [
        ClickResponse(
            id=c.id,
            referrer_url=c.referrer_url,
            contact_id=c.contact_id,
            clicked_at=c.clicked_at,
            converted_at=c.converted_at,
        )
        for c in clicks
    ]


# ---------------------------------------------------------------------------
# Public route — click tracking + redirect
# ---------------------------------------------------------------------------

@public_router.get("/{link_key}")
def track_and_redirect(link_key: str, request: Request, db: Session = Depends(get_db)):
    link = cts_service.get_link_by_key(db, link_key)
    if not link:
        raise HTTPException(status_code=404, detail="Link not found or inactive.")

    referrer = request.headers.get("Referer")
    ua = request.headers.get("User-Agent")
    ip = request.client.host if request.client else None

    cts_service.record_click(db, link, referrer_url=referrer, user_agent=ua, ip_address=ip)
    return RedirectResponse(url=cts_service.build_channel_url(link), status_code=302)
