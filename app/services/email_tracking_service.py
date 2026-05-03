import re
import uuid
from datetime import datetime
from typing import Optional, Tuple
from sqlalchemy.orm import Session

from app.models.email_tracking import EmailTrackingToken, TrackingTokenType
from app.core.config import settings


def _base_url() -> str:
    """Backend base URL used for embedding tracking links."""
    host = getattr(settings, 'PUBLIC_HOST', None) or getattr(settings, 'FRONTEND_URL', 'http://localhost:8000')
    # Strip trailing slash; tracking endpoints live on the backend
    return host.rstrip('/')


def create_open_token(
    db: Session,
    company_id: int,
    email_subject: str,
    sent_by: int,
    contact_id: Optional[int] = None,
    deal_id: Optional[int] = None,
    campaign_id: Optional[int] = None,
    campaign_message_id: Optional[int] = None,
) -> EmailTrackingToken:
    token = EmailTrackingToken(
        company_id=company_id,
        token=str(uuid.uuid4()),
        token_type=TrackingTokenType.OPEN,
        contact_id=contact_id,
        deal_id=deal_id,
        campaign_id=campaign_id,
        campaign_message_id=campaign_message_id,
        email_subject=email_subject,
        sent_by=sent_by,
    )
    db.add(token)
    db.flush()
    return token


def create_click_token(
    db: Session,
    company_id: int,
    original_url: str,
    email_subject: str,
    sent_by: int,
    contact_id: Optional[int] = None,
    deal_id: Optional[int] = None,
    campaign_id: Optional[int] = None,
    campaign_message_id: Optional[int] = None,
) -> EmailTrackingToken:
    token = EmailTrackingToken(
        company_id=company_id,
        token=str(uuid.uuid4()),
        token_type=TrackingTokenType.CLICK,
        contact_id=contact_id,
        deal_id=deal_id,
        campaign_id=campaign_id,
        campaign_message_id=campaign_message_id,
        original_url=original_url,
        email_subject=email_subject,
        sent_by=sent_by,
    )
    db.add(token)
    db.flush()
    return token


def inject_tracking(
    db: Session,
    html_body: str,
    plain_body: str,
    subject: str,
    company_id: int,
    sent_by: int,
    contact_id: Optional[int] = None,
    deal_id: Optional[int] = None,
    campaign_id: Optional[int] = None,
    campaign_message_id: Optional[int] = None,
) -> Tuple[str, str, EmailTrackingToken]:
    """
    Injects open pixel and wraps all links in click-tracking redirects.
    Returns (tracked_html, plain_body_unchanged, open_token).
    """
    base = _base_url()

    open_token = create_open_token(
        db=db, company_id=company_id, email_subject=subject, sent_by=sent_by,
        contact_id=contact_id, deal_id=deal_id,
        campaign_id=campaign_id, campaign_message_id=campaign_message_id,
    )
    pixel_url = f"{base}/api/v1/tracking/open/{open_token.token}"
    pixel_tag = f'<img src="{pixel_url}" width="1" height="1" alt="" style="display:none" />'

    # Wrap all <a href="..."> links (skip mailto:, tel:, and already-tracked links)
    def replace_link(match):
        href = match.group(1)
        if href.startswith(('mailto:', 'tel:', '#')) or '/api/v1/tracking/' in href:
            return match.group(0)
        click_token = create_click_token(
            db=db, company_id=company_id, original_url=href, email_subject=subject, sent_by=sent_by,
            contact_id=contact_id, deal_id=deal_id,
            campaign_id=campaign_id, campaign_message_id=campaign_message_id,
        )
        redirect_url = f"{base}/api/v1/tracking/click/{click_token.token}"
        return match.group(0).replace(href, redirect_url)

    tracked_html = re.sub(r'<a\s[^>]*href=["\']([^"\']+)["\']', replace_link, html_body, flags=re.IGNORECASE)

    # Append pixel before </body> or at end
    if '</body>' in tracked_html.lower():
        tracked_html = re.sub(r'</body>', f'{pixel_tag}</body>', tracked_html, flags=re.IGNORECASE)
    else:
        tracked_html += pixel_tag

    db.commit()
    return tracked_html, plain_body, open_token


def record_fire(
    db: Session,
    token_str: str,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> Optional[EmailTrackingToken]:
    token = db.query(EmailTrackingToken).filter(EmailTrackingToken.token == token_str).first()
    if not token:
        return None
    now = datetime.utcnow()
    if token.first_fired_at is None:
        token.first_fired_at = now
    token.last_fired_at = now
    token.fire_count = (token.fire_count or 0) + 1
    if ip_address:
        token.last_ip = ip_address
    if user_agent:
        token.last_user_agent = user_agent
    db.commit()
    return token


def get_tracking_summary(db: Session, company_id: int, contact_id: int) -> dict:
    """Returns open/click counts for all emails sent to a contact."""
    tokens = db.query(EmailTrackingToken).filter(
        EmailTrackingToken.company_id == company_id,
        EmailTrackingToken.contact_id == contact_id,
    ).all()

    opens = [t for t in tokens if t.token_type == TrackingTokenType.OPEN and t.fire_count > 0]
    clicks = [t for t in tokens if t.token_type == TrackingTokenType.CLICK and t.fire_count > 0]

    return {
        "emails_sent": len([t for t in tokens if t.token_type == TrackingTokenType.OPEN]),
        "emails_opened": len(opens),
        "total_opens": sum(t.fire_count for t in opens),
        "links_clicked": len(clicks),
        "total_clicks": sum(t.fire_count for t in clicks),
        "events": [
            {
                "type": t.token_type,
                "subject": t.email_subject,
                "url": t.original_url,
                "first_fired_at": t.first_fired_at,
                "fire_count": t.fire_count,
            }
            for t in sorted(tokens, key=lambda x: x.created_at, reverse=True)
            if t.fire_count > 0
        ],
    }
