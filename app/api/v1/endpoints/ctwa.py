"""
CTWA (Click to WhatsApp) endpoints

Protected:
  POST   /ctwa              — create link
  GET    /ctwa              — list links
  GET    /ctwa/{id}         — get link
  PUT    /ctwa/{id}         — update link
  DELETE /ctwa/{id}         — delete link
  GET    /ctwa/{id}/clicks  — click log

Public (no auth):
  GET    /public/ctwa/{key} — record click + redirect to WhatsApp
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
from app.services import ctwa_service

router = APIRouter()
public_router = APIRouter()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class LinkCreate(BaseModel):
    name: str
    phone_number: str
    prefill_message: Optional[str] = None
    utm_source: Optional[str] = None
    utm_medium: Optional[str] = None
    utm_campaign: Optional[str] = None
    utm_content: Optional[str] = None
    auto_tag: Optional[str] = None
    workflow_id: Optional[int] = None


class LinkUpdate(BaseModel):
    name: Optional[str] = None
    phone_number: Optional[str] = None
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
    name: str
    phone_number: str
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
    wa_url: str


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
        name=link.name,
        phone_number=link.phone_number,
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
        short_url=ctwa_service.build_short_url(link, backend_url),
        wa_url=ctwa_service.build_wa_url(link),
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
    link = ctwa_service.create_link(db, company_id=x_company_id, **body.model_dump())
    return _to_response(link)


@router.get("", response_model=List[LinkResponse])
def list_links(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
    x_company_id: int = Header(...),
):
    return [_to_response(l) for l in ctwa_service.list_links(db, x_company_id)]


@router.get("/{link_id}", response_model=LinkResponse)
def get_link(
    link_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
    x_company_id: int = Header(...),
):
    link = ctwa_service.get_link(db, link_id, x_company_id)
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
    link = ctwa_service.update_link(db, link_id, x_company_id, **body.model_dump(exclude_none=True))
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
    if not ctwa_service.delete_link(db, link_id, x_company_id):
        raise HTTPException(status_code=404, detail="Link not found.")


@router.get("/{link_id}/clicks", response_model=List[ClickResponse])
def get_clicks(
    link_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
    x_company_id: int = Header(...),
):
    link = ctwa_service.get_link(db, link_id, x_company_id)
    if not link:
        raise HTTPException(status_code=404, detail="Link not found.")
    clicks = ctwa_service.list_clicks(db, link_id, x_company_id)
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
    """Record click, then redirect to the WhatsApp deep link."""
    link = ctwa_service.get_link_by_key(db, link_key)
    if not link:
        raise HTTPException(status_code=404, detail="Link not found or inactive.")

    referrer = request.headers.get("Referer")
    ua = request.headers.get("User-Agent")
    ip = request.client.host if request.client else None

    ctwa_service.record_click(db, link, referrer_url=referrer, user_agent=ua, ip_address=ip)

    wa_url = ctwa_service.build_wa_url(link)
    return RedirectResponse(url=wa_url, status_code=302)
