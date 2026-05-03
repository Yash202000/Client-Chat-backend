"""
Public (no-auth) tracking endpoints for email open pixels and click redirects.
Also exposes an authenticated summary endpoint for the UI.
"""
import base64
from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from typing import Optional

from app.core.dependencies import get_db, get_current_active_user
from app.services import email_tracking_service
from app.models import user as models_user

router = APIRouter()

# 1×1 transparent GIF (43 bytes)
_PIXEL_GIF = base64.b64decode(
    "R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"
)


@router.get("/open/{token}")
def track_open(token: str, request: Request, db: Session = Depends(get_db)):
    """Called when the email client loads the tracking pixel."""
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")
    email_tracking_service.record_fire(db=db, token_str=token, ip_address=ip, user_agent=ua)
    return Response(content=_PIXEL_GIF, media_type="image/gif", headers={
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0",
    })


@router.get("/click/{token}")
def track_click(token: str, request: Request, db: Session = Depends(get_db)):
    """Records a link click and redirects to the original URL."""
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")
    tracked = email_tracking_service.record_fire(db=db, token_str=token, ip_address=ip, user_agent=ua)
    destination = (tracked.original_url if tracked and tracked.original_url else "/")
    return RedirectResponse(url=destination, status_code=302)


@router.get("/summary/contact/{contact_id}")
def get_contact_tracking_summary(
    contact_id: int,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user),
):
    """Returns open/click summary for all emails sent to a contact."""
    return email_tracking_service.get_tracking_summary(
        db=db, company_id=current_user.company_id, contact_id=contact_id
    )
