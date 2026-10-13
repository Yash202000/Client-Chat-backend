"""
Missed and abandoned calls (FR-CC-035..040, BR-005).

When an inbound call that needed a human ends without one, it is classified:
  abandoned      caller hung up while waiting, after the abandon threshold
  short_abandon  caller hung up within the threshold (excluded: no task)
  missed         nobody answered (overflow, ring timeout, no agents)
Each missed / abandoned call gets one callback task; a supervisor can assign it, agents call back
(each attempt logged) and the task closes only with an approved result.
"""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models.call_event import CallEvent
from app.models.call_queue import CallQueueEntry
from app.models.contact_center import CallbackAttempt, MissedCallTask
from app.models.conversation_session import ConversationSession
from app.models.user import User
from app.models.voice_call import VoiceCall

RESULTS = ("answered", "no_answer", "invalid_number", "refused", "resolved_elsewhere")


class TaskError(ValueError):
    pass


def classify(db: Session, call: VoiceCall) -> Optional[MissedCallTask]:
    """Called once when an inbound call's record is closed. Returns the new task, if any."""
    from app.services.outbound_service import get_settings

    if call.direction != "inbound" or call.manual_entry or call.handled_by_user_id:
        return None
    entry = db.query(CallQueueEntry).filter(CallQueueEntry.voice_call_id == call.id).order_by(CallQueueEntry.id).first()
    session = db.query(ConversationSession).filter(ConversationSession.conversation_id == call.conversation_id).first()
    direct = (call.call_metadata or {}).get("routing_mode") == "direct"
    wanted_human = bool(entry) or direct or bool(session and session.handoff_requested_at)
    if not wanted_human:
        return None  # the AI / IVR handled it completely

    cc = get_settings(db, call.company_id)
    waited_from = entry.entered_at if entry else (session.handoff_requested_at if session and session.handoff_requested_at else call.started_at)
    end = call.ended_at or datetime.utcnow()
    wait = max((end - waited_from).total_seconds(), 0) if waited_from else None
    if call.ended_by == "caller":
        classification = "abandoned" if (wait or 0) >= cc.abandon_threshold_seconds else "short_abandon"
        loss = "caller_hung_up_in_queue" if entry else "caller_hung_up_while_ringing"
    else:
        classification = "missed"
        events = {t for (t,) in db.query(CallEvent.type).filter(CallEvent.call_id == call.id).all()}
        loss = "overflow" if "overflow" in events else ("no_agent_answered" if entry else "ring_timeout")
    call.missed_classification = classification
    db.commit()
    from app.services import call_service
    call_service.record_event(db, call, "missed_classified",
                              payload={"classification": classification, "loss_reason": loss, "wait_seconds": wait})
    if classification == "short_abandon" or not cc.create_callback_tasks:
        return None
    task = MissedCallTask(company_id=call.company_id, call_id=call.id, caller_number=call.from_number,
                          contact_id=call.contact_id, queue_id=call.queue_id, classification=classification,
                          loss_reason=loss, wait_seconds=wait, status="open")
    db.add(task)
    db.commit()
    return task


def serialize(task: MissedCallTask, names: Optional[dict] = None) -> dict:
    names = names or {}
    return {
        "id": task.id, "call_id": task.call_id, "caller_number": task.caller_number, "contact_id": task.contact_id,
        "queue_id": task.queue_id, "classification": task.classification, "loss_reason": task.loss_reason,
        "wait_seconds": task.wait_seconds, "status": task.status, "assigned_to_user_id": task.assigned_to_user_id,
        "assigned_to": names.get(task.assigned_to_user_id), "assigned_at": task.assigned_at.isoformat() if task.assigned_at else None,
        "result": task.result, "result_comment": task.result_comment, "attempts": task.attempts,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "closed_at": task.closed_at.isoformat() if task.closed_at else None,
    }


def assign(db: Session, task: MissedCallTask, assignee_id: Optional[int], by_user_id: int) -> MissedCallTask:
    if task.status == "closed":
        raise TaskError("This task is closed")
    if assignee_id is not None and not db.query(User.id).filter(User.id == assignee_id, User.company_id == task.company_id).first():
        raise TaskError("Unknown agent")
    task.assigned_to_user_id = assignee_id
    task.assigned_by_user_id = by_user_id
    task.assigned_at = datetime.now(timezone.utc) if assignee_id else None
    task.status = "assigned" if assignee_id else "open"
    from app.core.audit import log_action
    log_action(db, task.company_id, by_user_id, "missed_call.assigned", entity_type="missed_call_task", entity_id=task.id,
               changes={"assigned_to_user_id": assignee_id})
    db.commit()
    return task


def close(db: Session, task: MissedCallTask, user_id: int, result: str, comment: Optional[str]) -> MissedCallTask:
    from app.services.outbound_service import get_settings

    if task.status == "closed":
        raise TaskError("This task is already closed")
    if result not in RESULTS:
        raise TaskError(f"Result must be one of: {', '.join(RESULTS)}")
    if result == "refused" and get_settings(db, task.company_id).refusal_comment_required and not (comment or "").strip():
        raise TaskError("A comment is required when the caller refused")
    task.status, task.result, task.result_comment = "closed", result, comment
    task.closed_at = datetime.now(timezone.utc)
    task.closed_by_user_id = user_id
    from app.core.audit import log_action
    log_action(db, task.company_id, user_id, "missed_call.closed", entity_type="missed_call_task", entity_id=task.id,
               changes={"result": result})
    db.commit()
    return task


def workload(db: Session, company_id: int) -> list[dict]:
    """Per agent: assigned (open), completed and attempts (FR-CC-040)."""
    rows = {}
    for t in db.query(MissedCallTask).filter(MissedCallTask.company_id == company_id, MissedCallTask.assigned_to_user_id.isnot(None)).all():
        r = rows.setdefault(t.assigned_to_user_id, {"user_id": t.assigned_to_user_id, "open": 0, "completed": 0, "attempts": 0})
        r["completed" if t.status == "closed" else "open"] += 1
        r["attempts"] += t.attempts or 0
    return list(rows.values())


def attempts(db: Session, task: MissedCallTask) -> list[dict]:
    return [{"id": a.id, "user_id": a.user_id, "voice_call_id": a.voice_call_id, "result": a.result,
             "started_at": a.started_at.isoformat() if a.started_at else None,
             "ended_at": a.ended_at.isoformat() if a.ended_at else None, "duration_seconds": a.duration_seconds}
            for a in db.query(CallbackAttempt).filter(CallbackAttempt.task_id == task.id).order_by(CallbackAttempt.id)]
