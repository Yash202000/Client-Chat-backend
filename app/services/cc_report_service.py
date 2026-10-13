"""
Contact-centre reports (BRD section 12: RPT-01..05, 07..10). Every report reads the same records
the operation writes (voice_calls, call_events, call_legs, call_queue_entries, agent_state_history,
missed_call_tasks, qa_evaluations), so KPIs and detail rows agree for the same filters (FR-DASH-002).

Each report returns {"title", "columns": [{key, label}], "rows": [...], "summary": {...}}.
"""
from collections import defaultdict
from datetime import datetime, time, timedelta, timezone
from typing import Callable, Optional

from sqlalchemy.orm import Session

from app.models.call_event import CallEvent, CallLeg
from app.models.call_queue import CallQueueEntry
from app.models.contact_center import (
    AgentReasonCode, AgentStateHistory, CallQueue, DispositionCode, MissedCallTask, QaEvaluation, QaForm,
)
from app.models.user import User
from app.models.voice_call import VoiceCall


class Filters:
    def __init__(self, company_id: int, date_from: Optional[str], date_to: Optional[str],
                 queue_id: Optional[int] = None, agent_id: Optional[int] = None, direction: Optional[str] = None):
        today = datetime.utcnow().date()
        d_from = datetime.fromisoformat(date_from).date() if date_from else today - timedelta(days=6)
        d_to = datetime.fromisoformat(date_to).date() if date_to else today
        self.company_id = company_id
        self.start = datetime.combine(d_from, time.min)       # naive UTC, like voice_calls
        self.end = datetime.combine(d_to, time.max)
        self.start_tz = self.start.replace(tzinfo=timezone.utc)
        self.end_tz = self.end.replace(tzinfo=timezone.utc)
        self.queue_id, self.agent_id, self.direction = queue_id, agent_id, direction


def _names(db: Session, company_id: int) -> dict:
    return {u.id: (" ".join(x for x in [u.first_name, u.last_name] if x) or u.email)
            for u in db.query(User).filter(User.company_id == company_id).all()}


def _calls(db: Session, f: Filters):
    q = db.query(VoiceCall).filter(VoiceCall.company_id == f.company_id, VoiceCall.provider.in_(("livekit_sip", "manual")),
                                   VoiceCall.started_at.between(f.start, f.end))
    if f.queue_id:
        q = q.filter(VoiceCall.queue_id == f.queue_id)
    if f.agent_id:
        q = q.filter(VoiceCall.handled_by_user_id == f.agent_id)
    if f.direction:
        q = q.filter(VoiceCall.direction == f.direction)
    return q.order_by(VoiceCall.started_at.desc()).all()


def _avg(values) -> Optional[float]:
    values = [v for v in values if v is not None]
    return round(sum(values) / len(values), 1) if values else None


def _iso(dt) -> Optional[str]:
    return dt.isoformat() if dt else None


def call_log(db: Session, f: Filters) -> dict:
    """RPT-01: every call with its parties, times and result."""
    names = _names(db, f.company_id)
    queues = {q.id: q.name for q in db.query(CallQueue).filter(CallQueue.company_id == f.company_id).all()}
    dispo = {d.id: d.name for d in db.query(DispositionCode).filter(DispositionCode.company_id == f.company_id).all()}
    rows = [{
        "id": c.id, "started_at": _iso(c.started_at), "direction": c.direction, "caller": c.from_number, "called": c.to_number,
        "queue": queues.get(c.queue_id), "agent": names.get(c.handled_by_user_id), "status": c.status, "ended_by": c.ended_by,
        "talk_seconds": c.talk_seconds, "hold_seconds": c.hold_seconds, "wrap_up_seconds": c.wrap_up_seconds,
        "result": dispo.get(c.disposition_code_id) or c.outbound_result or c.missed_classification,
        "recording": c.recording_status, "manual": bool(c.manual_entry),
    } for c in _calls(db, f)]
    cols = ["id", "started_at", "direction", "caller", "called", "queue", "agent", "status", "ended_by", "talk_seconds",
            "hold_seconds", "wrap_up_seconds", "result", "recording", "manual"]
    return {"title": "Call log", "columns": cols, "rows": rows,
            "summary": {"calls": len(rows), "answered": sum(1 for r in rows if r["talk_seconds"]),
                        "avg_talk_seconds": _avg(r["talk_seconds"] for r in rows)}}


def inbound_by_queue(db: Session, f: Filters) -> dict:
    """RPT-02: offered / answered / abandoned per queue, service level and average speed of answer."""
    from app.services.outbound_service import get_settings
    sl = get_settings(db, f.company_id).service_level_seconds
    q = db.query(CallQueueEntry, CallQueue.name).join(CallQueue, CallQueue.id == CallQueueEntry.queue_id) \
        .filter(CallQueueEntry.company_id == f.company_id, CallQueueEntry.source == "livekit_sip",
                CallQueueEntry.entered_at.between(f.start, f.end))
    if f.queue_id:
        q = q.filter(CallQueueEntry.queue_id == f.queue_id)
    per = defaultdict(lambda: {"offered": 0, "answered": 0, "abandoned": 0, "within_sl": 0, "answer_waits": [], "abandon_waits": []})
    for e, name in q.all():
        r = per[name]
        r["offered"] += 1
        if e.connected_at:
            r["answered"] += 1
            wait = (e.connected_at - e.entered_at).total_seconds()
            r["answer_waits"].append(wait)
            r["within_sl"] += wait <= sl
        elif e.status == "abandoned":
            r["abandoned"] += 1
            if e.ended_at:
                r["abandon_waits"].append((e.ended_at - e.entered_at).total_seconds())
    rows = [{"queue": name, "offered": r["offered"], "answered": r["answered"], "abandoned": r["abandoned"],
             "service_level_pct": round(100 * r["within_sl"] / r["offered"], 1) if r["offered"] else None,
             "avg_speed_of_answer_s": _avg(r["answer_waits"]), "avg_abandon_wait_s": _avg(r["abandon_waits"])}
            for name, r in sorted(per.items())]
    total = sum(r["offered"] for r in rows)
    return {"title": "Inbound calls by queue", "columns": list(rows[0].keys()) if rows else
            ["queue", "offered", "answered", "abandoned", "service_level_pct", "avg_speed_of_answer_s", "avg_abandon_wait_s"],
            "rows": rows, "summary": {"offered": total, "answered": sum(r["answered"] for r in rows),
                                      "abandoned": sum(r["abandoned"] for r in rows), "service_level_threshold_s": sl}}


def missed_calls(db: Session, f: Filters) -> dict:
    """RPT-03: every call that wasn't answered, with loss reason and handling status."""
    names = _names(db, f.company_id)
    tasks = {t.call_id: t for t in db.query(MissedCallTask).filter(MissedCallTask.company_id == f.company_id).all()}
    rows = []
    for c in _calls(db, f):
        if not c.missed_classification:
            continue
        t = tasks.get(c.id)
        rows.append({"started_at": _iso(c.started_at), "caller": c.from_number, "classification": c.missed_classification,
                     "loss_reason": t.loss_reason if t else None, "wait_seconds": round(t.wait_seconds, 1) if t and t.wait_seconds else None,
                     "assigned_to": names.get(t.assigned_to_user_id) if t else None, "attempts": t.attempts if t else 0,
                     "task_status": t.status if t else "no task", "result": t.result if t else None})
    by_class = defaultdict(int)
    for r in rows:
        by_class[r["classification"]] += 1
    return {"title": "Missed and abandoned calls", "columns": list(rows[0].keys()) if rows else
            ["started_at", "caller", "classification", "loss_reason", "wait_seconds", "assigned_to", "attempts", "task_status", "result"],
            "rows": rows, "summary": dict(by_class)}


def missed_followup(db: Session, f: Filters) -> dict:
    """RPT-04: missed-call follow-up per agent."""
    names = _names(db, f.company_id)
    q = db.query(MissedCallTask).filter(MissedCallTask.company_id == f.company_id,
                                        MissedCallTask.created_at.between(f.start_tz, f.end_tz))
    if f.agent_id:
        q = q.filter(MissedCallTask.assigned_to_user_id == f.agent_id)
    per = defaultdict(lambda: {"assigned": 0, "open": 0, "closed": 0, "attempts": 0, "last_result": None, "last_at": None})
    for t in q.all():
        r = per[t.assigned_to_user_id]
        r["assigned"] += 1
        r["closed" if t.status == "closed" else "open"] += 1
        r["attempts"] += t.attempts or 0
        if t.closed_at and (r["last_at"] is None or t.closed_at > r["last_at"]):
            r["last_at"], r["last_result"] = t.closed_at, t.result
    rows = [{"agent": names.get(uid) or "Unassigned", **{k: v for k, v in r.items() if k != "last_at"}} for uid, r in per.items()]
    return {"title": "Missed-call follow-up by agent", "columns": ["agent", "assigned", "open", "closed", "attempts", "last_result"],
            "rows": rows, "summary": {"tasks": sum(r["assigned"] for r in rows), "open": sum(r["open"] for r in rows)}}


def transfers(db: Session, f: Filters) -> dict:
    """RPT-05: direct and consultative transfers and their outcome."""
    names = _names(db, f.company_id)
    q = db.query(CallEvent, VoiceCall).join(VoiceCall, VoiceCall.id == CallEvent.call_id) \
        .filter(VoiceCall.company_id == f.company_id, CallEvent.type == "transfer", CallEvent.at.between(f.start_tz, f.end_tz))
    if f.agent_id:
        q = q.filter(CallEvent.actor_user_id == f.agent_id)
    failed = {cid for (cid,) in db.query(CallEvent.call_id).filter(CallEvent.type == "transfer_failed").all()}
    rows = [{"at": _iso(e.at), "call_id": c.id, "caller": c.from_number, "from_agent": names.get(e.actor_user_id),
             "type": (e.payload or {}).get("type"), "to": (e.payload or {}).get("to"),
             "result": "returned (not answered)" if c.id in failed else ("completed" if c.status == "completed" else c.status),
             "final_agent": names.get(c.handled_by_user_id)} for e, c in q.order_by(CallEvent.at.desc()).all()]
    return {"title": "Call transfers", "columns": ["at", "call_id", "caller", "from_agent", "type", "to", "result", "final_agent"],
            "rows": rows, "summary": {"transfers": len(rows), "returned": sum(1 for r in rows if r["result"].startswith("returned"))}}


def agent_status(db: Session, f: Filters) -> dict:
    """RPT-07: time each agent spent in each status (clipped to the period)."""
    names = _names(db, f.company_id)
    reasons = {r.id: r.name for r in db.query(AgentReasonCode).filter(AgentReasonCode.company_id == f.company_id).all()}
    q = db.query(AgentStateHistory).filter(AgentStateHistory.company_id == f.company_id,
                                           AgentStateHistory.started_at <= f.end_tz,
                                           (AgentStateHistory.ended_at.is_(None)) | (AgentStateHistory.ended_at >= f.start_tz))
    if f.agent_id:
        q = q.filter(AgentStateHistory.user_id == f.agent_id)
    now = datetime.now(timezone.utc)
    per = defaultdict(lambda: defaultdict(float))
    for h in q.all():
        start, end = max(h.started_at, f.start_tz), min(h.ended_at or now, f.end_tz)
        if end > start:
            label = h.state if not h.reason_code_id else f"{h.state}: {reasons.get(h.reason_code_id, '?')}"
            per[h.user_id][label] += (end - start).total_seconds()
    rows = [{"agent": names.get(uid), "status": label, "seconds": round(secs), "hours": round(secs / 3600, 2)}
            for uid, states in per.items() for label, secs in sorted(states.items())]
    return {"title": "Agent statuses", "columns": ["agent", "status", "seconds", "hours"], "rows": rows,
            "summary": {"agents": len(per)}}


def productivity(db: Session, f: Filters) -> dict:
    """RPT-08: calls handled, outbound calls, average talk / hold / wrap-up, missed offers, transfers."""
    names = _names(db, f.company_id)
    per = defaultdict(lambda: {"inbound": 0, "outbound": 0, "talk": [], "hold": [], "wrap": [], "missed_offers": 0, "transfers": 0})
    for c in _calls(db, f):
        if not c.handled_by_user_id or not c.answered_at:
            continue
        r = per[c.handled_by_user_id]
        r["outbound" if c.direction == "outbound" else "inbound"] += 1
        r["talk"].append(c.talk_seconds)
        r["hold"].append(c.hold_seconds)
        r["wrap"].append(c.wrap_up_seconds)
    for e in db.query(CallEvent).join(VoiceCall, VoiceCall.id == CallEvent.call_id).filter(
            VoiceCall.company_id == f.company_id, CallEvent.type.in_(("offer_timeout", "transfer")),
            CallEvent.at.between(f.start_tz, f.end_tz)).all():
        if e.actor_user_id:
            per[e.actor_user_id]["missed_offers" if e.type == "offer_timeout" else "transfers"] += 1
    rows = [{"agent": names.get(uid), "inbound_calls": r["inbound"], "outbound_calls": r["outbound"],
             "avg_talk_s": _avg(r["talk"]), "avg_hold_s": _avg(r["hold"]), "avg_wrap_up_s": _avg(r["wrap"]),
             "total_talk_min": round(sum(x or 0 for x in r["talk"]) / 60, 1), "missed_offers": r["missed_offers"],
             "transfers": r["transfers"]} for uid, r in per.items() if not f.agent_id or uid == f.agent_id]
    return {"title": "Agent productivity", "columns": ["agent", "inbound_calls", "outbound_calls", "avg_talk_s", "avg_hold_s",
                                                       "avg_wrap_up_s", "total_talk_min", "missed_offers", "transfers"],
            "rows": rows, "summary": {"agents": len(rows)}}


def call_quality(db: Session, f: Filters) -> dict:
    """RPT-09: evaluation results, notes and improvement plans."""
    names = _names(db, f.company_id)
    forms = {x.id: x.name for x in db.query(QaForm).filter(QaForm.company_id == f.company_id).all()}
    q = db.query(QaEvaluation).filter(QaEvaluation.company_id == f.company_id, QaEvaluation.status == "completed",
                                      QaEvaluation.completed_at.between(f.start_tz, f.end_tz))
    if f.agent_id:
        q = q.filter(QaEvaluation.agent_user_id == f.agent_id)
    rows = [{"completed_at": _iso(e.completed_at), "agent": names.get(e.agent_user_id), "call_id": e.call_id,
             "form": forms.get(e.form_id), "score_pct": e.total_score, "passed": e.passed,
             "evaluator": names.get(e.evaluator_user_id), "notes": e.notes, "improvement_plan": e.improvement_plan}
            for e in q.order_by(QaEvaluation.completed_at.desc()).all()]
    return {"title": "Call quality", "columns": ["completed_at", "agent", "call_id", "form", "score_pct", "passed", "evaluator",
                                                 "notes", "improvement_plan"],
            "rows": rows, "summary": {"evaluations": len(rows), "avg_score_pct": _avg(r["score_pct"] for r in rows),
                                      "pass_rate_pct": round(100 * sum(1 for r in rows if r["passed"]) / len(rows), 1) if rows else None}}


def recording_access(db: Session, f: Filters) -> dict:
    """RPT-10: who listened to / downloaded which recording."""
    names = _names(db, f.company_id)
    q = db.query(CallEvent, VoiceCall).join(VoiceCall, VoiceCall.id == CallEvent.call_id).filter(
        VoiceCall.company_id == f.company_id, CallEvent.type.in_(("recording_listen", "recording_download")),
        CallEvent.at.between(f.start_tz, f.end_tz))
    if f.agent_id:
        q = q.filter(CallEvent.actor_user_id == f.agent_id)
    rows = [{"at": _iso(e.at), "user": names.get(e.actor_user_id), "operation": e.type.replace("recording_", ""),
             "call_id": c.id, "caller": c.from_number} for e, c in q.order_by(CallEvent.at.desc()).all()]
    per_user = defaultdict(int)
    for r in rows:
        per_user[r["user"]] += 1
    return {"title": "Recording access", "columns": ["at", "user", "operation", "call_id", "caller"], "rows": rows,
            "summary": {"accesses": len(rows), "users": len(per_user),
                        "top_user": max(per_user.items(), key=lambda x: x[1])[0] if per_user else None}}


REPORTS: dict[str, tuple[str, Callable[[Session, Filters], dict]]] = {
    "call-log": ("RPT-01", call_log),
    "inbound-by-queue": ("RPT-02", inbound_by_queue),
    "missed-calls": ("RPT-03", missed_calls),
    "missed-followup": ("RPT-04", missed_followup),
    "transfers": ("RPT-05", transfers),
    "agent-status": ("RPT-07", agent_status),
    "productivity": ("RPT-08", productivity),
    "call-quality": ("RPT-09", call_quality),
    "recording-access": ("RPT-10", recording_access),
}


def run(db: Session, name: str, f: Filters) -> dict:
    code, fn = REPORTS[name]
    out = fn(db, f)
    out["code"] = code
    out["generated_at"] = datetime.now(timezone.utc).isoformat()
    out["source"] = "live call records"  # FR-DASH-007: data freshness / source
    out["period"] = {"from": f.start.date().isoformat(), "to": f.end.date().isoformat()}
    return out
