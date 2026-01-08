"""
Security Log Service

Service for logging and querying security events.
"""
import logging
from typing import Optional, List
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func, desc

from app.models.security_log import SecurityLog

logger = logging.getLogger(__name__)


def log_security_event(
    db: Session,
    event_type: str,
    threat_level: str,
    blocked: bool = True,
    company_id: Optional[int] = None,
    session_id: Optional[str] = None,
    original_message: Optional[str] = None,
    detected_patterns: Optional[List[str]] = None,
    sanitized_message: Optional[str] = None,
    channel: Optional[str] = None,
    user_ip: Optional[str] = None,
    user_agent: Optional[str] = None,
    additional_data: Optional[dict] = None
) -> SecurityLog:
    """
    Log a security event to the database.

    Args:
        db: Database session
        event_type: Type of event ("prompt_injection", "rate_limit", "output_leak", etc.)
        threat_level: Severity ("none", "low", "medium", "high", "critical")
        blocked: Whether the request was blocked
        company_id: Associated company ID
        session_id: Conversation session ID
        original_message: The original message that triggered the event
        detected_patterns: List of patterns that were matched
        sanitized_message: The sanitized version of the message
        channel: Channel (websocket, whatsapp, telegram, etc.)
        user_ip: User's IP address
        user_agent: User's browser/client agent
        additional_data: Any additional context

    Returns:
        The created SecurityLog record
    """
    try:
        # Truncate long messages to prevent DB issues
        if original_message and len(original_message) > 5000:
            original_message = original_message[:5000] + "... [truncated]"

        security_log = SecurityLog(
            event_type=event_type,
            threat_level=threat_level,
            blocked=1 if blocked else 0,
            company_id=company_id,
            session_id=session_id,
            original_message=original_message,
            detected_patterns=detected_patterns,
            sanitized_message=sanitized_message,
            channel=channel,
            user_ip=user_ip,
            user_agent=user_agent,
            additional_data=additional_data
        )

        db.add(security_log)
        db.commit()
        db.refresh(security_log)

        logger.info(
            f"[SecurityLog] Event logged: type={event_type}, threat={threat_level}, "
            f"blocked={blocked}, company={company_id}, session={session_id}"
        )

        return security_log

    except Exception as e:
        logger.error(f"[SecurityLog] Failed to log security event: {e}")
        db.rollback()
        return None


def get_security_logs(
    db: Session,
    company_id: Optional[int] = None,
    event_type: Optional[str] = None,
    threat_level: Optional[str] = None,
    blocked_only: bool = False,
    hours: int = 24,
    limit: int = 100,
    offset: int = 0
) -> List[SecurityLog]:
    """
    Query security logs with filters.

    Args:
        db: Database session
        company_id: Filter by company
        event_type: Filter by event type
        threat_level: Filter by threat level
        blocked_only: Only show blocked events
        hours: Time window in hours (default 24)
        limit: Maximum records to return
        offset: Pagination offset

    Returns:
        List of SecurityLog records
    """
    query = db.query(SecurityLog)

    # Apply filters
    if company_id:
        query = query.filter(SecurityLog.company_id == company_id)

    if event_type:
        query = query.filter(SecurityLog.event_type == event_type)

    if threat_level:
        query = query.filter(SecurityLog.threat_level == threat_level)

    if blocked_only:
        query = query.filter(SecurityLog.blocked == 1)

    # Time filter
    time_threshold = datetime.utcnow() - timedelta(hours=hours)
    query = query.filter(SecurityLog.created_at >= time_threshold)

    # Order by most recent first
    query = query.order_by(desc(SecurityLog.created_at))

    # Pagination
    query = query.offset(offset).limit(limit)

    return query.all()


def get_security_stats(
    db: Session,
    company_id: Optional[int] = None,
    hours: int = 24
) -> dict:
    """
    Get security statistics for dashboard.

    Args:
        db: Database session
        company_id: Filter by company
        hours: Time window in hours

    Returns:
        Dictionary with security statistics
    """
    time_threshold = datetime.utcnow() - timedelta(hours=hours)

    query = db.query(SecurityLog).filter(SecurityLog.created_at >= time_threshold)

    if company_id:
        query = query.filter(SecurityLog.company_id == company_id)

    # Total events
    total_events = query.count()

    # Events by type
    events_by_type = dict(
        db.query(SecurityLog.event_type, func.count(SecurityLog.id))
        .filter(SecurityLog.created_at >= time_threshold)
        .filter(SecurityLog.company_id == company_id if company_id else True)
        .group_by(SecurityLog.event_type)
        .all()
    )

    # Events by threat level
    events_by_threat = dict(
        db.query(SecurityLog.threat_level, func.count(SecurityLog.id))
        .filter(SecurityLog.created_at >= time_threshold)
        .filter(SecurityLog.company_id == company_id if company_id else True)
        .group_by(SecurityLog.threat_level)
        .all()
    )

    # Blocked vs allowed
    blocked_count = query.filter(SecurityLog.blocked == 1).count()
    allowed_count = total_events - blocked_count

    # Top attacking sessions (repeated attempts)
    top_sessions = (
        db.query(SecurityLog.session_id, func.count(SecurityLog.id).label('count'))
        .filter(SecurityLog.created_at >= time_threshold)
        .filter(SecurityLog.session_id.isnot(None))
        .filter(SecurityLog.company_id == company_id if company_id else True)
        .group_by(SecurityLog.session_id)
        .order_by(desc('count'))
        .limit(5)
        .all()
    )

    return {
        "time_window_hours": hours,
        "total_events": total_events,
        "blocked_count": blocked_count,
        "allowed_count": allowed_count,
        "block_rate": round(blocked_count / total_events * 100, 2) if total_events > 0 else 0,
        "events_by_type": events_by_type,
        "events_by_threat_level": events_by_threat,
        "top_suspicious_sessions": [
            {"session_id": s[0], "attempt_count": s[1]} for s in top_sessions
        ]
    }


def get_recent_critical_events(
    db: Session,
    company_id: Optional[int] = None,
    limit: int = 10
) -> List[SecurityLog]:
    """
    Get recent critical/high threat events for alerts.

    Args:
        db: Database session
        company_id: Filter by company
        limit: Maximum records to return

    Returns:
        List of critical SecurityLog records
    """
    query = db.query(SecurityLog).filter(
        SecurityLog.threat_level.in_(["critical", "high"])
    )

    if company_id:
        query = query.filter(SecurityLog.company_id == company_id)

    return query.order_by(desc(SecurityLog.created_at)).limit(limit).all()
