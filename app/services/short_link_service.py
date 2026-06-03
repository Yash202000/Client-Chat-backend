import datetime
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.short_link import ShortLink, generate_code


def create_short_link(
    db: Session,
    company_id: int,
    original_url: str,
    title: Optional[str] = None,
) -> ShortLink:
    """Generate a unique short code and persist the link."""
    for _ in range(5):
        code = generate_code()
        if not db.query(ShortLink).filter(ShortLink.code == code).first():
            break
    else:
        # Fallback: extend length to reduce collision probability
        import secrets, string
        alphabet = string.ascii_letters + string.digits
        code = ''.join(secrets.choice(alphabet) for _ in range(10))

    link = ShortLink(
        company_id=company_id,
        code=code,
        title=title,
        original_url=original_url,
    )
    db.add(link)
    db.commit()
    db.refresh(link)
    return link


def get_short_link_by_code(db: Session, code: str) -> Optional[ShortLink]:
    return db.query(ShortLink).filter(ShortLink.code == code).first()


def record_click(db: Session, link: ShortLink) -> None:
    link.click_count = (link.click_count or 0) + 1
    link.last_clicked_at = datetime.datetime.utcnow()
    db.commit()


def list_short_links(db: Session, company_id: int, limit: int = 50) -> List[ShortLink]:
    return (
        db.query(ShortLink)
        .filter(ShortLink.company_id == company_id)
        .order_by(ShortLink.created_at.desc())
        .limit(limit)
        .all()
    )


def delete_short_link(db: Session, link_id: int, company_id: int) -> bool:
    link = (
        db.query(ShortLink)
        .filter(ShortLink.id == link_id, ShortLink.company_id == company_id)
        .first()
    )
    if not link:
        return False
    db.delete(link)
    db.commit()
    return True


def toggle_active(db: Session, link_id: int, company_id: int) -> Optional[ShortLink]:
    link = (
        db.query(ShortLink)
        .filter(ShortLink.id == link_id, ShortLink.company_id == company_id)
        .first()
    )
    if not link:
        return None
    link.is_active = not link.is_active
    db.commit()
    db.refresh(link)
    return link
