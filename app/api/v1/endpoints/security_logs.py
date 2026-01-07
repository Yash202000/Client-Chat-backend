"""
Security Logs API Endpoints

Provides endpoints for viewing and managing security events.
"""
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from typing import Optional, List
from pydantic import BaseModel
from datetime import datetime

from app.core.dependencies import get_db, get_current_user
from app.services import security_log_service
from app.models.user import User

router = APIRouter()


# Response schemas
class SecurityLogResponse(BaseModel):
    id: int
    event_type: str
    threat_level: str
    blocked: bool
    company_id: Optional[int]
    session_id: Optional[str]
    original_message: Optional[str]
    detected_patterns: Optional[List[str]]
    channel: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class SecurityStatsResponse(BaseModel):
    time_window_hours: int
    total_events: int
    blocked_count: int
    allowed_count: int
    block_rate: float
    events_by_type: dict
    events_by_threat_level: dict
    top_suspicious_sessions: List[dict]


@router.get("/", response_model=List[SecurityLogResponse])
async def get_security_logs(
    event_type: Optional[str] = Query(None, description="Filter by event type (prompt_injection, rate_limit)"),
    threat_level: Optional[str] = Query(None, description="Filter by threat level (low, medium, high, critical)"),
    blocked_only: bool = Query(False, description="Only show blocked events"),
    hours: int = Query(24, ge=1, le=720, description="Time window in hours (max 30 days)"),
    limit: int = Query(100, ge=1, le=500, description="Maximum records to return"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get security logs for the current user's company.

    Requires authentication. Returns security events filtered by the specified criteria.
    """
    logs = security_log_service.get_security_logs(
        db=db,
        company_id=current_user.company_id,
        event_type=event_type,
        threat_level=threat_level,
        blocked_only=blocked_only,
        hours=hours,
        limit=limit,
        offset=offset
    )

    return [
        SecurityLogResponse(
            id=log.id,
            event_type=log.event_type,
            threat_level=log.threat_level,
            blocked=bool(log.blocked),
            company_id=log.company_id,
            session_id=log.session_id,
            original_message=log.original_message,
            detected_patterns=log.detected_patterns,
            channel=log.channel,
            created_at=log.created_at
        )
        for log in logs
    ]


@router.get("/stats", response_model=SecurityStatsResponse)
async def get_security_stats(
    hours: int = Query(24, ge=1, le=720, description="Time window in hours (max 30 days)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get security statistics for the dashboard.

    Returns aggregated statistics about security events including:
    - Total events and block rate
    - Events by type and threat level
    - Top suspicious sessions
    """
    stats = security_log_service.get_security_stats(
        db=db,
        company_id=current_user.company_id,
        hours=hours
    )

    return SecurityStatsResponse(**stats)


@router.get("/critical", response_model=List[SecurityLogResponse])
async def get_critical_events(
    limit: int = Query(10, ge=1, le=50, description="Maximum records to return"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get recent critical/high threat security events.

    Useful for security alerts and monitoring.
    """
    logs = security_log_service.get_recent_critical_events(
        db=db,
        company_id=current_user.company_id,
        limit=limit
    )

    return [
        SecurityLogResponse(
            id=log.id,
            event_type=log.event_type,
            threat_level=log.threat_level,
            blocked=bool(log.blocked),
            company_id=log.company_id,
            session_id=log.session_id,
            original_message=log.original_message,
            detected_patterns=log.detected_patterns,
            channel=log.channel,
            created_at=log.created_at
        )
        for log in logs
    ]


@router.delete("/{log_id}")
async def delete_security_log(
    log_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Delete a specific security log entry.

    Only logs belonging to the user's company can be deleted.
    """
    from app.models.security_log import SecurityLog

    log = db.query(SecurityLog).filter(
        SecurityLog.id == log_id,
        SecurityLog.company_id == current_user.company_id
    ).first()

    if not log:
        raise HTTPException(status_code=404, detail="Security log not found")

    db.delete(log)
    db.commit()

    return {"message": "Security log deleted successfully"}


@router.delete("/")
async def clear_old_logs(
    older_than_days: int = Query(30, ge=7, le=365, description="Delete logs older than X days"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Clear old security logs.

    Deletes logs older than the specified number of days (minimum 7 days).
    Only affects logs for the current user's company.
    """
    from app.models.security_log import SecurityLog
    from datetime import timedelta

    cutoff_date = datetime.utcnow() - timedelta(days=older_than_days)

    deleted_count = db.query(SecurityLog).filter(
        SecurityLog.company_id == current_user.company_id,
        SecurityLog.created_at < cutoff_date
    ).delete()

    db.commit()

    return {"message": f"Deleted {deleted_count} old security logs"}
