from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc, func, or_
from app.core.dependencies import get_db
from app.models import conversation_session as models_conversation_session
from app.models import agent as models_agent
from app.models import chat_message as models_chat_message
from typing import Dict, Any, List
from app.models.user import User
from app.core.auth import get_current_user
import datetime

router = APIRouter()

@router.get("/metrics")
def get_overall_metrics(
    db: Session = Depends(get_db),
    start_date: datetime.date = Query(None),
    end_date: datetime.date = Query(None),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:

    # Convert end_date to include the entire day (23:59:59)
    end_datetime = datetime.datetime.combine(end_date, datetime.time.max) if end_date else None

    query = db.query(models_conversation_session.ConversationSession)
    query = query.filter(models_conversation_session.ConversationSession.company_id == current_user.company_id)
    if start_date:
        query = query.filter(models_conversation_session.ConversationSession.created_at >= start_date)
    if end_datetime:
        query = query.filter(models_conversation_session.ConversationSession.created_at <= end_datetime)

    total_conversations = query.count()

    # Active conversations (not resolved or archived)
    active_conversations = db.query(models_conversation_session.ConversationSession).filter(
        models_conversation_session.ConversationSession.company_id == current_user.company_id,
        ~models_conversation_session.ConversationSession.status.in_(['resolved', 'archived'])
    )
    if start_date:
        active_conversations = active_conversations.filter(models_conversation_session.ConversationSession.created_at >= start_date)
    if end_datetime:
        active_conversations = active_conversations.filter(models_conversation_session.ConversationSession.created_at <= end_datetime)
    active_conversations_count = active_conversations.count()

    # Resolved conversations count
    resolved_conversations = db.query(models_conversation_session.ConversationSession).filter(
        models_conversation_session.ConversationSession.company_id == current_user.company_id,
        models_conversation_session.ConversationSession.status == 'resolved'
    )
    if start_date:
        resolved_conversations = resolved_conversations.filter(models_conversation_session.ConversationSession.created_at >= start_date)
    if end_datetime:
        resolved_conversations = resolved_conversations.filter(models_conversation_session.ConversationSession.created_at <= end_datetime)
    resolved_conversations_count = resolved_conversations.count()

    # Resolution rate
    resolution_rate = round((resolved_conversations_count / total_conversations) * 100, 2) if total_conversations > 0 else 0

    # Unattended conversations (no assignee or waiting for agent)
    unattended_conversations = db.query(models_conversation_session.ConversationSession).filter(
        models_conversation_session.ConversationSession.company_id == current_user.company_id,
        or_(
            models_conversation_session.ConversationSession.assignee_id.is_(None),
            models_conversation_session.ConversationSession.waiting_for_agent == True
        ),
        ~models_conversation_session.ConversationSession.status.in_(['resolved', 'archived'])
    )
    if start_date:
        unattended_conversations = unattended_conversations.filter(models_conversation_session.ConversationSession.created_at >= start_date)
    if end_datetime:
        unattended_conversations = unattended_conversations.filter(models_conversation_session.ConversationSession.created_at <= end_datetime)
    unattended_conversations_count = unattended_conversations.count()

    avg_satisfaction_query = db.query(func.avg(models_chat_message.ChatMessage.feedback_rating))
    avg_satisfaction_query = avg_satisfaction_query.filter(models_chat_message.ChatMessage.company_id == current_user.company_id)
    if start_date:
        avg_satisfaction_query = avg_satisfaction_query.filter(models_chat_message.ChatMessage.timestamp >= start_date)
    if end_datetime:
        avg_satisfaction_query = avg_satisfaction_query.filter(models_chat_message.ChatMessage.timestamp <= end_datetime)
    avg_satisfaction = avg_satisfaction_query.scalar() or 0

    active_agents = db.query(models_agent.Agent).filter(models_agent.Agent.is_active == True).count()

    # Agent availability (users who are online)
    available_users = db.query(User).filter(
        User.company_id == current_user.company_id,
        User.is_active == True,
        User.presence_status == 'online'
    ).count()

    total_users = db.query(User).filter(
        User.company_id == current_user.company_id,
        User.is_active == True
    ).count()

    agent_availability_rate = round((available_users / total_users) * 100, 2) if total_users > 0 else 0

    return {
        "total_sessions": total_conversations,
        "customer_satisfaction": round(avg_satisfaction, 2),
        "active_agents": active_agents,
        "active_conversations": active_conversations_count,
        "resolution_rate": f"{resolution_rate}%",
        "available_users": available_users,
        "total_users": total_users,
        "agent_availability_rate": f"{agent_availability_rate}%",
        "unattended_conversations": unattended_conversations_count,
    }

@router.get("/agent-performance")
def get_agent_performance(
    db: Session = Depends(get_db),
    start_date: datetime.date = Query(None),
    end_date: datetime.date = Query(None),
    current_user: User = Depends(get_current_user),
) -> List[Dict[str, Any]]:
    # Convert end_date to include the entire day (23:59:59)
    end_datetime = datetime.datetime.combine(end_date, datetime.time.max) if end_date else None

    query = db.query(
        models_agent.Agent.name,
        func.count(models_conversation_session.ConversationSession.id).label('conversations'),
        func.avg(models_chat_message.ChatMessage.feedback_rating).label('satisfaction')
    ).join(
        models_conversation_session.ConversationSession,
        models_agent.Agent.id == models_conversation_session.ConversationSession.agent_id
    ).join(
        models_chat_message.ChatMessage,
        models_conversation_session.ConversationSession.id == models_chat_message.ChatMessage.session_id
    )

    if start_date:
        query = query.filter(models_conversation_session.ConversationSession.created_at >= start_date)
    if end_datetime:
        query = query.filter(models_conversation_session.ConversationSession.created_at <= end_datetime)
        
    performance_data = query.group_by(models_agent.Agent.name).all()
    
    return [
        {
            "agent_name": name,
            "conversations": conversations,
            "satisfaction": round(satisfaction, 2) if satisfaction else 0,
            "avg_response": "N/A" # Placeholder
        }
        for name, conversations, satisfaction in performance_data
    ]

@router.get("/customer-satisfaction")
def get_customer_satisfaction(
    db: Session = Depends(get_db),
    start_date: datetime.date = Query(None),
    end_date: datetime.date = Query(None),
    current_user: User = Depends(get_current_user),
) -> List[Dict[str, Any]]:
    # Convert end_date to include the entire day (23:59:59)
    end_datetime = datetime.datetime.combine(end_date, datetime.time.max) if end_date else None

    query = db.query(
        models_chat_message.ChatMessage.feedback_rating,
        func.count(models_chat_message.ChatMessage.id).label('count')
    ).filter(models_chat_message.ChatMessage.feedback_rating != None)

    if start_date:
        query = query.filter(models_chat_message.ChatMessage.timestamp >= start_date)
    if end_datetime:
        query = query.filter(models_chat_message.ChatMessage.timestamp <= end_datetime)

    satisfaction_data = query.group_by(models_chat_message.ChatMessage.feedback_rating).all()
    
    total_ratings = sum([item.count for item in satisfaction_data])
    
    return [
        {
            "rating": rating,
            "percentage": round((count / total_ratings) * 100, 2) if total_ratings > 0 else 0
        }
        for rating, count in satisfaction_data
    ]

@router.get("/top-issues")
def get_top_issues(
    db: Session = Depends(get_db),
    start_date: datetime.date = Query(None),
    end_date: datetime.date = Query(None),
    current_user: User = Depends(get_current_user),
) -> List[Dict[str, Any]]:
    # Convert end_date to include the entire day (23:59:59)
    end_datetime = datetime.datetime.combine(end_date, datetime.time.max) if end_date else None

    query = db.query(
        models_chat_message.ChatMessage.issue,
        func.count(models_chat_message.ChatMessage.id).label('count')
    ).filter(models_chat_message.ChatMessage.issue != None)

    if start_date:
        query = query.filter(models_chat_message.ChatMessage.timestamp >= start_date)
    if end_datetime:
        query = query.filter(models_chat_message.ChatMessage.timestamp <= end_datetime)

    top_issues_data = query.group_by(models_chat_message.ChatMessage.issue).order_by(desc('count')).limit(10).all()
    
    return [
        {
            "issue": issue,
            "count": count
        }
        for issue, count in top_issues_data
    ]

@router.get("/error-rates")
def get_error_rates(
    db: Session = Depends(get_db),
    start_date: datetime.date = Query(None),
    end_date: datetime.date = Query(None),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    # Placeholder - requires error logging mechanism
    return {"overall_error_rate": "5.2%"}

@router.get("/latency")
def get_latency(
    db: Session = Depends(get_db),
    start_date: datetime.date = Query(None),
    end_date: datetime.date = Query(None),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    # Convert end_date to include the entire day (23:59:59)
    end_datetime = datetime.datetime.combine(end_date, datetime.time.max) if end_date else None

    query = db.query(models_chat_message.ChatMessage).order_by(models_chat_message.ChatMessage.timestamp)
    if start_date:
        query = query.filter(models_chat_message.ChatMessage.timestamp >= start_date)
    if end_datetime:
        query = query.filter(models_chat_message.ChatMessage.timestamp <= end_datetime)
        
    messages = query.all()
    
    response_times = []
    sessions = {}
    for msg in messages:
        if msg.session_id not in sessions:
            sessions[msg.session_id] = []
        sessions[msg.session_id].append(msg)
        
    for session_id, session_messages in sessions.items():
        for i in range(len(session_messages) - 1):
            current_msg = session_messages[i]
            next_msg = session_messages[i+1]
            if current_msg.sender == 'user' and next_msg.sender == 'agent':
                response_time = next_msg.timestamp - current_msg.timestamp
                response_times.append(response_time.total_seconds())
                
    if not response_times:
        return {"avg_response_time": "N/A"}
        
    avg_response_seconds = sum(response_times) / len(response_times)
    
    minutes, seconds = divmod(avg_response_seconds, 60)
    
    return {"avg_response_time": f"{int(minutes)}m {int(seconds)}s"}

@router.get("/conversation-status")
def get_conversation_status(
    db: Session = Depends(get_db),
    start_date: datetime.date = Query(None),
    end_date: datetime.date = Query(None),
    current_user: User = Depends(get_current_user),
) -> List[Dict[str, Any]]:
    """
    Get conversation counts grouped by status (active, inactive, assigned, pending, resolved, archived)
    """
    # Convert end_date to include the entire day (23:59:59)
    end_datetime = datetime.datetime.combine(end_date, datetime.time.max) if end_date else None

    query = db.query(
        models_conversation_session.ConversationSession.status,
        func.count(models_conversation_session.ConversationSession.id).label('count')
    ).filter(models_conversation_session.ConversationSession.company_id == current_user.company_id)

    if start_date:
        query = query.filter(models_conversation_session.ConversationSession.created_at >= start_date)
    if end_datetime:
        query = query.filter(models_conversation_session.ConversationSession.created_at <= end_datetime)

    status_data = query.group_by(models_conversation_session.ConversationSession.status).all()

    total_conversations = sum([item.count for item in status_data])

    return [
        {
            "status": status,
            "count": count,
            "percentage": round((count / total_conversations) * 100, 2) if total_conversations > 0 else 0
        }
        for status, count in status_data
    ]

@router.get("/conversation-trends")
def get_conversation_trends(
    db: Session = Depends(get_db),
    start_date: datetime.date = Query(None),
    end_date: datetime.date = Query(None),
    current_user: User = Depends(get_current_user),
) -> List[Dict[str, Any]]:
    """
    Get daily conversation counts for trend analysis
    """
    # Convert end_date to include the entire day (23:59:59)
    end_datetime = datetime.datetime.combine(end_date, datetime.time.max) if end_date else None

    query = db.query(
        func.date(models_conversation_session.ConversationSession.created_at).label('date'),
        func.count(models_conversation_session.ConversationSession.id).label('count')
    ).filter(models_conversation_session.ConversationSession.company_id == current_user.company_id)

    if start_date:
        query = query.filter(models_conversation_session.ConversationSession.created_at >= start_date)
    if end_datetime:
        query = query.filter(models_conversation_session.ConversationSession.created_at <= end_datetime)

    trends_data = query.group_by(func.date(models_conversation_session.ConversationSession.created_at)).order_by('date').all()

    return [
        {
            "date": str(date),
            "count": count
        }
        for date, count in trends_data
    ]

@router.get("/channel-distribution")
def get_channel_distribution(
    db: Session = Depends(get_db),
    start_date: datetime.date = Query(None),
    end_date: datetime.date = Query(None),
    current_user: User = Depends(get_current_user),
) -> List[Dict[str, Any]]:
    """
    Get conversation counts grouped by channel (web, whatsapp, messenger, instagram, telegram, gmail)
    """
    # Convert end_date to include the entire day (23:59:59)
    end_datetime = datetime.datetime.combine(end_date, datetime.time.max) if end_date else None

    query = db.query(
        models_conversation_session.ConversationSession.channel,
        func.count(models_conversation_session.ConversationSession.id).label('count')
    ).filter(models_conversation_session.ConversationSession.company_id == current_user.company_id)

    if start_date:
        query = query.filter(models_conversation_session.ConversationSession.created_at >= start_date)
    if end_datetime:
        query = query.filter(models_conversation_session.ConversationSession.created_at <= end_datetime)

    channel_data = query.group_by(models_conversation_session.ConversationSession.channel).all()

    total_conversations = sum([item.count for item in channel_data])

    return [
        {
            "channel": channel,
            "count": count,
            "percentage": round((count / total_conversations) * 100, 2) if total_conversations > 0 else 0
        }
        for channel, count in channel_data
    ]

@router.get("/summary")
def get_reports_summary(
    db: Session = Depends(get_db),
    days: int = Query(30, ge=1, le=365),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Unified summary endpoint for the reports dashboard."""
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=days)
    company_id = current_user.company_id

    CS = models_conversation_session.ConversationSession

    # Total sessions in period
    total_sessions = db.query(func.count(CS.id)).filter(
        CS.company_id == company_id,
        CS.created_at >= cutoff
    ).scalar() or 0

    # Resolved sessions
    resolved_sessions = db.query(func.count(CS.id)).filter(
        CS.company_id == company_id,
        CS.created_at >= cutoff,
        CS.status == 'resolved'
    ).scalar() or 0

    resolution_rate = round((resolved_sessions / total_sessions * 100), 1) if total_sessions > 0 else 0

    # Sessions per channel
    channel_rows = db.query(
        CS.channel,
        func.count(CS.id).label('count')
    ).filter(
        CS.company_id == company_id,
        CS.created_at >= cutoff
    ).group_by(CS.channel).all()
    sessions_per_channel = [{"channel": ch or "unknown", "count": cnt} for ch, cnt in channel_rows]

    # Sessions by status
    status_rows = db.query(
        CS.status,
        func.count(CS.id).label('count')
    ).filter(
        CS.company_id == company_id,
        CS.created_at >= cutoff
    ).group_by(CS.status).all()
    sessions_by_status = [{"status": st, "count": cnt} for st, cnt in status_rows]

    # Daily volume (last N days)
    daily_rows = db.query(
        func.date(CS.created_at).label('date'),
        func.count(CS.id).label('count')
    ).filter(
        CS.company_id == company_id,
        CS.created_at >= cutoff
    ).group_by(func.date(CS.created_at)).order_by('date').all()
    daily_volume = [{"date": str(d), "count": cnt} for d, cnt in daily_rows]

    # Sessions per agent (top agents)
    agent_rows = db.query(
        User.email,
        func.count(CS.id).label('count')
    ).join(CS, User.id == CS.assignee_id).filter(
        CS.company_id == company_id,
        CS.created_at >= cutoff,
        CS.assignee_id.isnot(None)
    ).group_by(User.id, User.email).order_by(desc('count')).limit(10).all()
    sessions_per_agent = [{"agent": email, "count": cnt} for email, cnt in agent_rows]

    return {
        "total_sessions": total_sessions,
        "resolved_sessions": resolved_sessions,
        "resolution_rate": resolution_rate,
        "sessions_per_channel": sessions_per_channel,
        "sessions_by_status": sessions_by_status,
        "daily_volume": daily_volume,
        "sessions_per_agent": sessions_per_agent,
        "days": days,
    }

@router.get("/alerts")
def get_alerts(db: Session = Depends(get_db),current_user: User = Depends(get_current_user),) -> List[Dict[str, Any]]:
    # Placeholder - requires an alerting system
    return [
        {"id": 1, "message": "High error rate detected in payment gateway.", "timestamp": "2025-08-15T14:30:00Z", "type": "critical"},
        {"id": 2, "message": "Customer satisfaction dropped below 80%.", "timestamp": "2025-08-15T10:00:00Z", "type": "warning"},
    ]
