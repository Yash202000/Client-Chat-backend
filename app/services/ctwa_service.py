"""
Click to WhatsApp (CTWA) Service

Flow:
  1. Company creates a CTWA link via dashboard → gets a short URL
  2. They embed that URL anywhere (website, ads, emails, bio links)
  3. Visitor hits GET /public/ctwa/{key} → click recorded → redirect to wa.me deep link
  4. Visitor sends first WhatsApp message
  5. WhatsApp webhook calls attribute_ctwa_contact() → contact tagged + workflow triggered
"""
import logging
import secrets
import urllib.parse
from datetime import datetime
from typing import Optional, List

from sqlalchemy.orm import Session

from app.models.ctwa_link import CTWALink, CTWAClick

logger = logging.getLogger(__name__)


def _gen_key() -> str:
    return secrets.token_urlsafe(8)  # ~11 char URL-safe key


def build_wa_url(link: CTWALink) -> str:
    phone = link.phone_number.replace("+", "").replace(" ", "").replace("-", "")
    url = f"https://wa.me/{phone}"
    params = {}
    if link.prefill_message:
        params["text"] = link.prefill_message
    if params:
        url += "?" + urllib.parse.urlencode(params)
    return url


def build_short_url(link: CTWALink, backend_url: str) -> str:
    return f"{backend_url}/api/v1/public/ctwa/{link.link_key}"


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def create_link(
    db: Session,
    company_id: int,
    name: str,
    phone_number: str,
    prefill_message: Optional[str] = None,
    utm_source: Optional[str] = None,
    utm_medium: Optional[str] = None,
    utm_campaign: Optional[str] = None,
    utm_content: Optional[str] = None,
    auto_tag: Optional[str] = None,
    workflow_id: Optional[int] = None,
) -> CTWALink:
    link = CTWALink(
        link_key=_gen_key(),
        company_id=company_id,
        name=name,
        phone_number=phone_number,
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


def get_link(db: Session, link_id: int, company_id: int) -> Optional[CTWALink]:
    return db.query(CTWALink).filter(
        CTWALink.id == link_id, CTWALink.company_id == company_id
    ).first()


def get_link_by_key(db: Session, link_key: str) -> Optional[CTWALink]:
    return db.query(CTWALink).filter(
        CTWALink.link_key == link_key, CTWALink.is_active == True
    ).first()


def list_links(db: Session, company_id: int) -> List[CTWALink]:
    return db.query(CTWALink).filter(
        CTWALink.company_id == company_id
    ).order_by(CTWALink.created_at.desc()).all()


def update_link(db: Session, link_id: int, company_id: int, **kwargs) -> Optional[CTWALink]:
    link = get_link(db, link_id, company_id)
    if not link:
        return None
    for k, v in kwargs.items():
        if hasattr(link, k) and v is not None:
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
) -> List[CTWAClick]:
    return (
        db.query(CTWAClick)
        .filter(CTWAClick.link_id == link_id, CTWAClick.company_id == company_id)
        .order_by(CTWAClick.clicked_at.desc())
        .limit(limit)
        .all()
    )


# ---------------------------------------------------------------------------
# Click tracking
# ---------------------------------------------------------------------------

def record_click(
    db: Session,
    link: CTWALink,
    referrer_url: Optional[str] = None,
    user_agent: Optional[str] = None,
    ip_address: Optional[str] = None,
) -> CTWAClick:
    click = CTWAClick(
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
    logger.info(f"[CTWA] Click recorded — link '{link.name}' (key={link.link_key})")
    return click


# ---------------------------------------------------------------------------
# Attribution — called from WhatsApp webhook on first message
# ---------------------------------------------------------------------------

async def attribute_ctwa_contact(
    db: Session,
    company_id: int,
    sender_phone: str,
    contact,  # Contact ORM object (already created by webhook)
) -> None:
    """
    Find the most recent unattributed CTWA click for this company and tag the contact.
    Called by the WhatsApp webhook after contact is created/retrieved.
    """
    # Find latest unattributed click for this company
    # We match on company since we can't reliably correlate click → WA sender without Meta CTWA params
    unattributed = (
        db.query(CTWAClick)
        .filter(
            CTWAClick.company_id == company_id,
            CTWAClick.contact_id == None,
            CTWAClick.converted_at == None,
        )
        .order_by(CTWAClick.clicked_at.desc())
        .first()
    )

    if not unattributed:
        return

    link = unattributed.link

    # Mark click as converted
    unattributed.contact_id = contact.id
    unattributed.converted_at = datetime.utcnow()
    link.contact_count = (link.contact_count or 0) + 1

    # Apply lead_source if not already set
    if not contact.lead_source:
        contact.lead_source = f"ctwa:{link.name}"

    # Auto-tag the contact
    tag_name = link.auto_tag or f"ctwa-{link.name.lower().replace(' ', '-')}"
    await _apply_tag(db, contact, tag_name, company_id)

    # Also tag with utm_campaign if set
    if link.utm_campaign:
        await _apply_tag(db, contact, f"utm-{link.utm_campaign}", company_id)

    db.commit()
    logger.info(f"[CTWA] Attributed contact {contact.id} to link '{link.name}'")

    # Trigger linked workflow if configured
    if link.workflow_id:
        await _trigger_workflow(db, link, contact, company_id)


async def _apply_tag(db: Session, contact, tag_name: str, company_id: int) -> None:
    from app.models.tag import Tag
    from app.models.contact import Contact as ContactModel

    tag = db.query(Tag).filter(
        Tag.name == tag_name, Tag.company_id == company_id
    ).first()
    if not tag:
        tag = Tag(name=tag_name, company_id=company_id)
        db.add(tag)
        db.flush()

    if tag not in contact.tags:
        contact.tags.append(tag)


async def _trigger_workflow(db: Session, link: CTWALink, contact, company_id: int) -> None:
    try:
        from app.services import workflow_service
        workflow = workflow_service.get_workflow(db, link.workflow_id, company_id)
        if workflow and workflow.is_active:
            logger.info(f"[CTWA] Workflow {link.workflow_id} triggered for contact {contact.id}")
    except Exception as e:
        logger.warning(f"[CTWA] Workflow trigger failed: {e}")
