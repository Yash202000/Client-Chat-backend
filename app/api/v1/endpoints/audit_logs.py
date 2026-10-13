"""
Audit Logs API Endpoints

Provides endpoints for viewing the company audit trail.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session, joinedload
from typing import Optional, List
from pydantic import BaseModel
from datetime import datetime

from app.core.dependencies import get_db, require_permission
from app.models.audit_log import AuditLog
from app.models.user import User

router = APIRouter()


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class AuditLogUserInfo(BaseModel):
    id: int
    full_name: Optional[str] = None
    email: Optional[str] = None

    class Config:
        from_attributes = True


class AuditLogResponse(BaseModel):
    id: int
    company_id: int
    user_id: Optional[int] = None
    user: Optional[AuditLogUserInfo] = None
    action: str
    entity_type: Optional[str] = None
    entity_id: Optional[int] = None
    entity_name: Optional[str] = None
    changes: Optional[dict] = None
    ip_address: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/", response_model=List[AuditLogResponse])
async def list_audit_logs(
    entity_type: Optional[str] = Query(None, description="Filter by entity type (contact, lead, deal, …)"),
    action: Optional[str] = Query(None, description="Filter by action (e.g. contact.created)"),
    user_id: Optional[int] = Query(None, description="Filter by user who performed the action"),
    date_from: Optional[datetime] = Query(None, description="Start of date range (ISO-8601)"),
    date_to: Optional[datetime] = Query(None, description="End of date range (ISO-8601)"),
    skip: int = Query(0, ge=0, description="Pagination offset"),
    limit: int = Query(100, ge=1, le=500, description="Number of records"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("audit:read")),
):
    """
    Return audit log entries for the current user's company, newest first.

    Supports filtering by entity_type, action, user_id, and date range.
    """
    query = (
        db.query(AuditLog)
        .options(joinedload(AuditLog.user))
        .filter(AuditLog.company_id == current_user.company_id)
    )

    if entity_type:
        query = query.filter(AuditLog.entity_type == entity_type)
    if action:
        query = query.filter(AuditLog.action.ilike(f"%{action}%"))
    if user_id:
        query = query.filter(AuditLog.user_id == user_id)
    if date_from:
        query = query.filter(AuditLog.created_at >= date_from)
    if date_to:
        query = query.filter(AuditLog.created_at <= date_to)

    logs = (
        query
        .order_by(AuditLog.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    result = []
    for log in logs:
        user_info = None
        if log.user:
            first = log.user.first_name or ""
            last = log.user.last_name or ""
            full_name = (first + " " + last).strip() or log.user.email
            user_info = AuditLogUserInfo(
                id=log.user.id,
                full_name=full_name,
                email=log.user.email,
            )
        result.append(
            AuditLogResponse(
                id=log.id,
                company_id=log.company_id,
                user_id=log.user_id,
                user=user_info,
                action=log.action,
                entity_type=log.entity_type,
                entity_id=log.entity_id,
                entity_name=log.entity_name,
                changes=log.changes,
                ip_address=log.ip_address,
                created_at=log.created_at,
            )
        )

    return result


@router.get("/export", dependencies=[Depends(require_permission("audit:read"))])
def export_audit_logs(
    entity_type: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    user_id: Optional[int] = Query(None),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("reports:export")),
):
    """CSV export of the (read-only) audit log; the export itself is audited."""
    import csv
    import io
    from fastapi.responses import Response
    from app.core.audit import log_action

    q = db.query(AuditLog).filter(AuditLog.company_id == current_user.company_id)
    if entity_type:
        q = q.filter(AuditLog.entity_type == entity_type)
    if action:
        q = q.filter(AuditLog.action.ilike(f"%{action}%"))
    if user_id:
        q = q.filter(AuditLog.user_id == user_id)
    if date_from:
        q = q.filter(AuditLog.created_at >= date_from)
    if date_to:
        q = q.filter(AuditLog.created_at <= date_to)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["created_at", "user_id", "action", "entity_type", "entity_id", "entity_name", "changes", "ip"])
    for row in q.order_by(AuditLog.created_at.desc()).limit(50000):
        w.writerow([row.created_at.isoformat() if row.created_at else "", row.user_id, row.action, row.entity_type,
                    row.entity_id, row.entity_name, row.changes, row.ip_address])
    log_action(db, current_user.company_id, current_user.id, "audit_log.exported", entity_type="audit_log",
               changes={"entity_type": entity_type, "action": action})
    db.commit()
    return Response(buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="audit-log.csv"'})
