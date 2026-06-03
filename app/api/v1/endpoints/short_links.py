"""
Link Shortener endpoints

Protected (requires session auth):
  POST   /short-links              — create link
  GET    /short-links              — list links for company
  DELETE /short-links/{id}         — delete link
  PATCH  /short-links/{id}/toggle  — toggle active/inactive

Public (no auth):
  GET /s/{code} — look up link, record click, 302 redirect
"""
import logging
from typing import Optional, List
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, get_current_active_user
from app.models.user import User
from app.services import short_link_service

router = APIRouter()
public_router = APIRouter()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ShortLinkCreate(BaseModel):
    original_url: str
    title: Optional[str] = None


class ShortLinkResponse(BaseModel):
    id: int
    company_id: int
    code: str
    title: Optional[str]
    original_url: str
    click_count: int
    is_active: bool
    created_at: datetime
    last_clicked_at: Optional[datetime]

    class Config:
        from_attributes = True


def _to_response(link) -> ShortLinkResponse:
    return ShortLinkResponse(
        id=link.id,
        company_id=link.company_id,
        code=link.code,
        title=link.title,
        original_url=link.original_url,
        click_count=link.click_count or 0,
        is_active=link.is_active,
        created_at=link.created_at,
        last_clicked_at=link.last_clicked_at,
    )


# ---------------------------------------------------------------------------
# Protected endpoints
# ---------------------------------------------------------------------------

@router.post("", response_model=ShortLinkResponse, status_code=201)
def create_short_link(
    body: ShortLinkCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
    x_company_id: int = Header(...),
):
    link = short_link_service.create_short_link(
        db=db,
        company_id=x_company_id,
        original_url=body.original_url,
        title=body.title,
    )
    return _to_response(link)


@router.get("", response_model=List[ShortLinkResponse])
def list_short_links(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
    x_company_id: int = Header(...),
):
    links = short_link_service.list_short_links(db, x_company_id)
    return [_to_response(l) for l in links]


@router.delete("/{link_id}", status_code=204)
def delete_short_link(
    link_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
    x_company_id: int = Header(...),
):
    deleted = short_link_service.delete_short_link(db, link_id, x_company_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Link not found.")


@router.patch("/{link_id}/toggle", response_model=ShortLinkResponse)
def toggle_short_link(
    link_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
    x_company_id: int = Header(...),
):
    link = short_link_service.toggle_active(db, link_id, x_company_id)
    if not link:
        raise HTTPException(status_code=404, detail="Link not found.")
    return _to_response(link)


# ---------------------------------------------------------------------------
# Public redirect endpoint
# ---------------------------------------------------------------------------

@public_router.get("/{code}")
def redirect_short_link(
    code: str,
    db: Session = Depends(get_db),
):
    link = short_link_service.get_short_link_by_code(db, code)
    if not link or not link.is_active:
        raise HTTPException(status_code=404, detail="Link not found or inactive.")
    short_link_service.record_click(db, link)
    return RedirectResponse(url=link.original_url, status_code=302)
