"""
Voice Supervisor Dashboard endpoints.

GET /voice/supervisor/live   — real-time snapshot of calls, queue, agents
GET /voice/supervisor/analytics?days=30  — aggregated analytics
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, or_
from typing import List, Optional
from datetime import datetime, timedelta
import logging

from app.core.dependencies import get_db, get_current_active_user
from app.models.user import User
from app.models.voice_call import VoiceCall
from app.models.call_queue import CallQueueEntry

router = APIRouter()
logger = logging.getLogger(__name__)


# ── Live Dashboard ─────────────────────────────────────────────────────────────

@router.get("/live")
def supervisor_live(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Real-time supervisor snapshot: active calls, queue, agent presence."""
    company_id = current_user.company_id
    now = datetime.utcnow()

    # Active calls (in_progress)
    active_calls = (
        db.query(VoiceCall)
        .filter(VoiceCall.company_id == company_id, VoiceCall.status == "in_progress")
        .all()
    )

    active_calls_out = []
    for c in active_calls:
        duration = int((now - c.started_at).total_seconds()) if c.started_at else 0
        active_calls_out.append({
            "id": c.id,
            "call_sid": c.call_sid,
            "from_number": c.from_number,
            "to_number": c.to_number,
            "direction": c.direction,
            "status": c.status,
            "started_at": c.started_at.isoformat() if c.started_at else None,
            "duration_secs": duration,
            "contact_id": c.contact_id,
            "conversation_id": c.conversation_id,
        })

    # Queue (waiting)
    queue_entries = (
        db.query(CallQueueEntry)
        .filter(CallQueueEntry.company_id == company_id, CallQueueEntry.status == "waiting")
        .order_by(CallQueueEntry.priority.desc(), CallQueueEntry.entered_at.asc())
        .all()
    )

    queue_out = []
    for e in queue_entries:
        wait = int((now - e.entered_at).total_seconds()) if e.entered_at else 0
        queue_out.append({
            "id": e.id,
            "call_sid": e.call_sid,
            "caller_number": e.caller_number,
            "caller_name": e.caller_name,
            "status": e.status,
            "priority": e.priority,
            "required_skill": e.required_skill,
            "entered_at": e.entered_at.isoformat() if e.entered_at else None,
            "wait_secs": wait,
            "assigned_agent_id": e.assigned_agent_id,
        })

    # Agents (all in company with presence info)
    agents = (
        db.query(User)
        .filter(User.company_id == company_id, User.is_active == True)
        .all()
    )

    # Build map of call_sid -> agent_id from active calls
    agent_call_map = {}
    for c in active_calls:
        if c.conversation_id:
            # Try to get the agent from the connected queue entry
            pass

    # Also check queue entries for agent assignment
    connected_entries = (
        db.query(CallQueueEntry)
        .filter(
            CallQueueEntry.company_id == company_id,
            CallQueueEntry.status.in_(["connected", "ringing"]),
            CallQueueEntry.assigned_agent_id != None,
        )
        .all()
    )
    for ce in connected_entries:
        agent_call_map[ce.assigned_agent_id] = ce.call_sid

    agents_out = []
    for u in agents:
        agents_out.append({
            "id": u.id,
            "first_name": u.first_name,
            "last_name": u.last_name,
            "email": u.email,
            "presence_status": u.presence_status,
            "skills": u.skills,
            "current_call_sid": agent_call_map.get(u.id),
        })

    return {
        "active_calls": active_calls_out,
        "queue": queue_out,
        "agents": agents_out,
        "snapshot_at": now.isoformat(),
    }


# ── Analytics ─────────────────────────────────────────────────────────────────

@router.get("/analytics")
def call_analytics(
    days: int = Query(default=30, ge=1, le=1825),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Aggregated call center analytics for the given number of days."""
    company_id = current_user.company_id
    since = datetime.utcnow() - timedelta(days=days)

    base = db.query(VoiceCall).filter(
        VoiceCall.company_id == company_id,
        or_(VoiceCall.started_at >= since, VoiceCall.started_at.is_(None)),
    )

    all_calls = base.all()
    total = len(all_calls)
    inbound = sum(1 for c in all_calls if c.direction == "inbound")
    outbound = sum(1 for c in all_calls if c.direction == "outbound")
    completed = sum(1 for c in all_calls if c.status == "completed")
    no_answer = sum(1 for c in all_calls if c.status == "no_answer")
    failed = sum(1 for c in all_calls if c.status == "failed")

    durations = [c.duration_seconds for c in all_calls if c.duration_seconds]
    avg_handle_time = sum(durations) / len(durations) if durations else 0.0

    # ASA — average wait time from queue
    queue_base = db.query(CallQueueEntry).filter(
        CallQueueEntry.company_id == company_id,
        CallQueueEntry.entered_at >= since,
        CallQueueEntry.connected_at != None,
    ).all()

    wait_times = []
    for e in queue_base:
        if e.connected_at and e.entered_at:
            wait_times.append((e.connected_at - e.entered_at).total_seconds())
    avg_asa = sum(wait_times) / len(wait_times) if wait_times else 0.0

    # Abandonment rate
    abandoned = sum(1 for c in all_calls if c.status in ("no_answer", "failed"))
    denom = abandoned + completed
    abandonment_rate = abandoned / denom if denom > 0 else 0.0

    # CSAT average
    csat_scores = [c.csat_score for c in all_calls if c.csat_score is not None]
    csat_avg = sum(csat_scores) / len(csat_scores) if csat_scores else 0.0

    # By day
    from collections import defaultdict
    day_map: dict = defaultdict(lambda: {"calls": 0, "completed": 0})
    for c in all_calls:
        ts = c.started_at or c.ended_at
        day_str = ts.strftime("%Y-%m-%d") if ts else "unknown"
        day_map[day_str]["calls"] += 1
        if c.status == "completed":
            day_map[day_str]["completed"] += 1
    by_day = [{"date": d, "calls": v["calls"], "completed": v["completed"]}
               for d, v in sorted(day_map.items())]

    # By agent — using assigned_agent_id from connected queue entries
    agent_entries = (
        db.query(CallQueueEntry)
        .filter(
            CallQueueEntry.company_id == company_id,
            CallQueueEntry.entered_at >= since,
            CallQueueEntry.assigned_agent_id != None,
        )
        .all()
    )

    agent_stats: dict = defaultdict(lambda: {"calls": 0, "durations": [], "name": ""})
    agent_users = {u.id: u for u in db.query(User).filter(User.company_id == company_id).all()}

    for e in agent_entries:
        aid = e.assigned_agent_id
        u = agent_users.get(aid)
        if u:
            name = f"{u.first_name or ''} {u.last_name or ''}".strip() or u.email
            agent_stats[aid]["name"] = name
        agent_stats[aid]["calls"] += 1
        # Try to get duration from matching voice call
        if e.call_sid:
            vc = db.query(VoiceCall).filter(VoiceCall.call_sid == e.call_sid).first()
            if vc and vc.duration_seconds:
                agent_stats[aid]["durations"].append(vc.duration_seconds)

    by_agent = []
    for aid, s in agent_stats.items():
        durs = s["durations"]
        by_agent.append({
            "agent_id": aid,
            "agent_name": s["name"],
            "calls": s["calls"],
            "avg_duration": sum(durs) / len(durs) if durs else 0.0,
        })
    by_agent.sort(key=lambda x: x["calls"], reverse=True)

    return {
        "total_calls": total,
        "inbound": inbound,
        "outbound": outbound,
        "completed": completed,
        "no_answer": no_answer,
        "failed": failed,
        "avg_handle_time_secs": round(avg_handle_time, 1),
        "avg_speed_to_answer_secs": round(avg_asa, 1),
        "abandonment_rate": round(abandonment_rate, 4),
        "csat_avg": round(csat_avg, 2),
        "by_day": by_day,
        "by_agent": by_agent,
    }
