"""
Audit utility

Usage:
    from app.core.audit import log_action
    log_action(db, company_id=1, user_id=5, action="contact.created",
               entity_type="contact", entity_id=42, entity_name="Jane Doe")
    db.commit()  # caller is responsible for committing
"""
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog


def log_action(
    db: Session,
    company_id: int,
    user_id: Optional[int],
    action: str,
    entity_type: Optional[str] = None,
    entity_id: Optional[int] = None,
    entity_name: Optional[str] = None,
    changes: Optional[Dict[str, Any]] = None,
    ip: Optional[str] = None,
) -> AuditLog:
    """
    Create an AuditLog entry and add it to the session.
    The caller is responsible for calling db.commit().
    """
    entry = AuditLog(
        company_id=company_id,
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        entity_name=entity_name,
        changes=changes,
        ip_address=ip,
    )
    db.add(entry)
    return entry
