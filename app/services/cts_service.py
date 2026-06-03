"""Click to Social (CTS) service — supports whatsapp, instagram, telegram, messenger."""
import logging
import secrets
import urllib.parse
from datetime import datetime
from typing import Optional, List

from sqlalchemy.orm import Session

from app.models.cts_link import CTSocialLink, CTSocialClick

logger = logging.getLogger(__name__)


def _gen_key() -> str:
    return secrets.token_urlsafe(8)


def build_channel_url(link: CTSocialLink) -> str:
    if link.channel == "whatsapp":
        phone = link.handle.replace("+", "").replace(" ", "").replace("-", "")
        url = f"https://wa.me/{phone}"
        if link.prefill_message:
            url += "?" + urllib.parse.urlencode({"text": link.prefill_message})
        return url
    if link.channel == "instagram":
        return f"https://ig.me/m/{link.handle}"
    if link.channel == "telegram":
        url = f"https://t.me/{link.handle}"
        if link.prefill_message:
            url += "?" + urllib.parse.urlencode({"start": link.prefill_message})
        return url
    if link.channel == "messenger":
        url = f"https://m.me/{link.handle}"
        if link.prefill_message:
            url += "?" + urllib.parse.urlencode({"ref": link.prefill_message})
        return url
    return f"https://wa.me/{link.handle}"


def build_short_url(link: CTSocialLink, backend_url: str) -> str:
    return f"{backend_url}/api/v1/public/cts/{link.link_key}"


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def create_link(
    db: Session,
    company_id: int,
    channel: str,
    name: str,
    handle: str,
    prefill_message: Optional[str] = None,
    utm_source: Optional[str] = None,
    utm_medium: Optional[str] = None,
    utm_campaign: Optional[str] = None,
    utm_content: Optional[str] = None,
    auto_tag: Optional[str] = None,
    workflow_id: Optional[int] = None,
) -> CTSocialLink:
    link = CTSocialLink(
        link_key=_gen_key(),
        company_id=company_id,
        channel=channel,
        name=name,
        handle=handle,
        prefill_message=prefill_message,
        utm_source=utm_source,
        utm_medium=utm_medium,
        utm_campaign=utm_campaign,
        utm_content=utm_content,
        auto_tag=auto_tag,
        workflow_id=workflow_id,
    )
    db.add(link)
    db.commit()
    db.refresh(link)
    return link


def get_link(db: Session, link_id: int, company_id: int) -> Optional[CTSocialLink]:
    return db.query(CTSocialLink).filter(
        CTSocialLink.id == link_id, CTSocialLink.company_id == company_id
    ).first()


def get_link_by_key(db: Session, link_key: str) -> Optional[CTSocialLink]:
    return db.query(CTSocialLink).filter(
        CTSocialLink.link_key == link_key, CTSocialLink.is_active == True
    ).first()


def list_links(
    db: Session, company_id: int, channel: Optional[str] = None
) -> List[CTSocialLink]:
    q = db.query(CTSocialLink).filter(CTSocialLink.company_id == company_id)
    if channel:
        q = q.filter(CTSocialLink.channel == channel)
    return q.order_by(CTSocialLink.created_at.desc()).all()


def update_link(db: Session, link_id: int, company_id: int, **kwargs) -> Optional[CTSocialLink]:
    link = get_link(db, link_id, company_id)
    if not link:
        return None
    for k, v in kwargs.items():
        if hasattr(link, k):
            setattr(link, k, v)
    db.commit()
    db.refresh(link)
    return link


def delete_link(db: Session, link_id: int, company_id: int) -> bool:
    link = get_link(db, link_id, company_id)
    if not link:
        return False
    db.delete(link)
    db.commit()
    return True


def list_clicks(
    db: Session, link_id: int, company_id: int, limit: int = 100
) -> List[CTSocialClick]:
    return (
        db.query(CTSocialClick)
        .filter(CTSocialClick.link_id == link_id, CTSocialClick.company_id == company_id)
        .order_by(CTSocialClick.clicked_at.desc())
        .limit(limit)
        .all()
    )


def record_click(
    db: Session,
    link: CTSocialLink,
    referrer_url: Optional[str] = None,
    user_agent: Optional[str] = None,
    ip_address: Optional[str] = None,
) -> CTSocialClick:
    click = CTSocialClick(
        link_id=link.id,
        company_id=link.company_id,
        referrer_url=referrer_url,
        user_agent=user_agent,
        ip_address=ip_address,
    )
    db.add(click)
    link.click_count = (link.click_count or 0) + 1
    db.commit()
    db.refresh(click)
    logger.info(f"[CTS] Click recorded — link '{link.name}' channel={link.channel}")
    return click
