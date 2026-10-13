"""
Quality evaluation (FR-CC-053, RPT-09) and data retention (FR-ADM-008).

QA: supervisors pick a sample of answered calls — random percentage or count, narrowed by agent,
queue, result and duration — and score each against a weighted form.

Retention: per company, recordings / call history / chat messages are kept for life by default or
for N >= 90 days. After a period is shortened nothing is removed for 7 days (grace), so a mistake
can be undone. Every purge run is written to the audit log.
"""
import logging
import random
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models.contact_center import ContactCenterSettings, QaEvaluation, QaForm
from app.models.voice_call import VoiceCall

logger = logging.getLogger(__name__)

MIN_RETENTION_DAYS = 90
GRACE_DAYS = 7


class QaError(ValueError):
    pass


# ---------------------------------------------------------------- QA

def sample_calls(db: Session, company_id: int, *, form_id: int, evaluator_id: int, count: Optional[int] = None,
                 percent: Optional[float] = None, agent_id: Optional[int] = None, queue_id: Optional[int] = None,
                 disposition_code_id: Optional[int] = None, min_talk_seconds: Optional[int] = None,
                 days: int = 7) -> list[QaEvaluation]:
    form = db.query(QaForm).filter(QaForm.id == form_id, QaForm.company_id == company_id, QaForm.is_active.is_(True)).first()
    if not form:
        raise QaError("Choose an active evaluation form")
    already = {cid for (cid,) in db.query(QaEvaluation.call_id).filter(QaEvaluation.company_id == company_id).all()}
    q = db.query(VoiceCall).filter(VoiceCall.company_id == company_id, VoiceCall.provider == "livekit_sip",
                                   VoiceCall.answered_at.isnot(None), VoiceCall.handled_by_user_id.isnot(None),
                                   VoiceCall.started_at >= datetime.utcnow() - timedelta(days=days))
    if agent_id:
        q = q.filter(VoiceCall.handled_by_user_id == agent_id)
    if queue_id:
        q = q.filter(VoiceCall.queue_id == queue_id)
    if disposition_code_id:
        q = q.filter(VoiceCall.disposition_code_id == disposition_code_id)
    if min_talk_seconds:
        q = q.filter(VoiceCall.talk_seconds >= min_talk_seconds)
    pool = [c for c in q.all() if c.id not in already]
    if percent:
        count = max(1, round(len(pool) * percent / 100)) if pool else 0
    count = min(count or 5, len(pool))
    batch = secrets.token_hex(4)
    chosen = random.sample(pool, count) if count else []
    evals = [QaEvaluation(company_id=company_id, form_id=form.id, call_id=c.id, agent_user_id=c.handled_by_user_id,
                          evaluator_user_id=evaluator_id, status="pending", scores={}, sample_batch=batch) for c in chosen]
    db.add_all(evals)
    db.commit()
    return evals


def complete(db: Session, ev: QaEvaluation, evaluator_id: int, scores: dict, notes: Optional[str],
             improvement_plan: Optional[str]) -> QaEvaluation:
    form = db.query(QaForm).filter(QaForm.id == ev.form_id).first()
    if not form:
        raise QaError("The evaluation form no longer exists")
    total_weight, earned = 0.0, 0.0
    for c in form.criteria or []:
        weight = float(c.get("weight", 1))
        value = float(scores.get(c["key"], 0))
        if not 0 <= value <= weight:
            raise QaError(f"'{c.get('label', c['key'])}' must be between 0 and {weight:g}")
        total_weight += weight
        earned += value
    ev.scores = {k: float(v) for k, v in scores.items()}
    ev.total_score = round(100 * earned / total_weight, 1) if total_weight else None
    ev.passed = ev.total_score is not None and ev.total_score >= form.pass_score
    ev.notes, ev.improvement_plan = notes, improvement_plan
    ev.status, ev.evaluator_user_id, ev.completed_at = "completed", evaluator_id, datetime.now(timezone.utc)
    db.commit()
    return ev


# ---------------------------------------------------------------- retention

def validate_days(value: Optional[int], label: str) -> None:
    if value is not None and value < MIN_RETENTION_DAYS:
        raise ValueError(f"{label} must be kept at least {MIN_RETENTION_DAYS} days (or for life)")


def purge_company(db: Session, cc: ContactCenterSettings, now: Optional[datetime] = None) -> dict:
    """Apply one company's retention periods. Returns counts; nothing happens during the grace period."""
    from app.core.audit import log_action
    from app.models.chat_message import ChatMessage
    from app.models.conversation_session import ConversationSession
    from app.services import call_service

    now = now or datetime.now(timezone.utc)
    result = {"recordings": 0, "calls": 0, "chat_messages": 0, "skipped": None}
    if cc.retention_changed_at and now - cc.retention_changed_at < timedelta(days=GRACE_DAYS):
        result["skipped"] = "grace period"
        return result
    naive_now = now.replace(tzinfo=None)

    if cc.recording_retention_days:
        cutoff = naive_now - timedelta(days=cc.recording_retention_days)
        from app.core.object_storage import BUCKET_NAME, s3_client
        from app.services import recording_service
        for call in db.query(VoiceCall).filter(VoiceCall.company_id == cc.company_id, VoiceCall.started_at < cutoff,
                                               VoiceCall.recording_object_key.isnot(None)).all():
            try:
                for key in recording_service.part_keys(call):  # every part of a paused recording
                    s3_client.delete_object(Bucket=BUCKET_NAME, Key=key)
            except Exception:
                logger.exception(f"[retention] could not delete recording of call {call.id}")
                continue
            call.recording_object_key, call.recording_status, call.recording_parts = None, "purged", []
            call_service.record_event(db, call, "recording_purged", payload={"retention_days": cc.recording_retention_days})
            result["recordings"] += 1
    if cc.call_history_retention_days:
        cutoff = naive_now - timedelta(days=cc.call_history_retention_days)
        old = db.query(VoiceCall).filter(VoiceCall.company_id == cc.company_id, VoiceCall.started_at < cutoff).all()
        for call in old:
            db.delete(call)  # events, legs, tasks and evaluations go with it (ON DELETE CASCADE)
        result["calls"] = len(old)
    if cc.chat_retention_days:
        cutoff = now - timedelta(days=cc.chat_retention_days)
        session_ids = db.query(ConversationSession.id).filter(ConversationSession.company_id == cc.company_id)
        result["chat_messages"] = db.query(ChatMessage).filter(ChatMessage.session_id.in_(session_ids),
                                                              ChatMessage.timestamp < cutoff).delete(synchronize_session=False)
    if any(result[k] for k in ("recordings", "calls", "chat_messages")):
        log_action(db, cc.company_id, None, "retention.purged", entity_type="contact_center", changes=result)
    db.commit()
    return result


async def run_retention_loop(interval_seconds: int = 3600) -> None:
    """Hourly check in the API process (cheap when nothing is due)."""
    import asyncio
    from app.core.database import SessionLocal

    while True:
        try:
            db = SessionLocal()
            try:
                for cc in db.query(ContactCenterSettings).filter(
                        (ContactCenterSettings.recording_retention_days.isnot(None))
                        | (ContactCenterSettings.call_history_retention_days.isnot(None))
                        | (ContactCenterSettings.chat_retention_days.isnot(None))).all():
                    purge_company(db, cc)
            finally:
                db.close()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("[retention] run failed")
        await asyncio.sleep(interval_seconds)
