"""
Integration test for contact-centre reports (RPT-01..10), exports, QA evaluation and data retention.
Builds a small known dataset in the dev database, checks the numbers, then removes everything.

Run from backend/:  python -m scripts.telephony_reports_test [--company-id 1]
"""
import argparse
import sys
import uuid
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.core.security import create_access_token
from app.models.audit_log import AuditLog
from app.models.call_event import CallEvent, CallLeg
from app.models.call_queue import CallQueueEntry
from app.models.contact_center import (
    AgentStateHistory, CallQueue, MissedCallTask, QaEvaluation, QaForm,
)
from app.models.role import Role
from app.models.user import User
from app.models.voice_call import VoiceCall
from app.services import call_service, qa_retention_service
from app.services.outbound_service import get_settings

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--company-id", type=int, default=1)
args = parser.parse_args()
failures = []


def check(name, cond, detail=""):
    print(f"  {'ok  ' if cond else 'FAIL'} {name}{(' -> ' + str(detail)) if detail and not cond else ''}")
    if not cond:
        failures.append(name)


def main():
    from app.main import app
    db = SessionLocal()
    cid, tag = args.company_id, uuid.uuid4().hex[:6]
    admin = (db.query(User).join(Role, User.role_id == Role.id)
             .filter(User.company_id == cid, Role.name == "Admin", User.is_active.is_(True)).order_by(User.id).first())
    agent = db.query(User).filter(User.email == "vikram.patel@grv.test").first() or admin
    now = datetime.utcnow()
    queue = CallQueue(company_id=cid, name=f"__rpt_{tag}")
    db.add(queue); db.commit()
    calls, extra = [], []

    def mk(i, *, answered, wait, handled_by=None, ended_by="agent", talk=60, hold=10, classification=None):
        start = now - timedelta(hours=1, minutes=i)
        c = VoiceCall(call_sid=f"RPT{i}_{tag}", provider="livekit_sip", room_name=f"call_rpt{i}_{tag}", from_number=f"+96650000{i:04d}",
                      to_number="980", company_id=cid, status="completed" if answered else "no_answer", direction="inbound",
                      started_at=start, answered_at=start + timedelta(seconds=wait) if answered else None,
                      ended_at=start + timedelta(seconds=wait + talk), handled_by_user_id=handled_by, queue_id=queue.id,
                      talk_seconds=talk if answered else None, hold_seconds=hold if answered else 0, ended_by=ended_by,
                      missed_classification=classification)
        db.add(c); db.flush()
        db.add(CallQueueEntry(company_id=cid, call_sid=c.call_sid, source="livekit_sip", caller_number=c.from_number,
                              status="connected" if answered else "abandoned", queue_id=queue.id, voice_call_id=c.id,
                              entered_at=start, connected_at=start + timedelta(seconds=wait) if answered else None,
                              ended_at=c.ended_at, declined_user_ids=[]))
        calls.append(c)
        return c

    a1 = mk(1, answered=True, wait=10, handled_by=agent.id)          # within 20s SL
    a2 = mk(2, answered=True, wait=40, handled_by=agent.id)          # outside SL
    a3 = mk(3, answered=True, wait=5, handled_by=admin.id)
    ab = mk(4, answered=False, wait=0, ended_by="caller", talk=30, classification="abandoned")
    db.commit()
    db.add(MissedCallTask(company_id=cid, call_id=ab.id, caller_number=ab.from_number, queue_id=queue.id, classification="abandoned",
                          loss_reason="caller_hung_up_in_queue", wait_seconds=30, status="assigned", assigned_to_user_id=agent.id, attempts=2))
    call_service.record_event(db, a1, "transfer", actor_type="agent", actor_user_id=agent.id, payload={"type": "blind", "to": "queue:Sales"})
    call_service.record_event(db, a3, "recording_listen", actor_type="agent", actor_user_id=admin.id)
    call_service.record_event(db, a3, "recording_download", actor_type="agent", actor_user_id=admin.id)
    from app.services import cc_report_service
    _f = cc_report_service.Filters(cid, now.date().isoformat(), now.date().isoformat(), agent_id=agent.id)
    baseline = {x["status"]: x["seconds"] for x in cc_report_service.agent_status(db, _f)["rows"]}
    t0 = datetime(now.year, now.month, now.day, tzinfo=timezone.utc) + timedelta(minutes=1)  # early today, before real activity
    hist = [AgentStateHistory(user_id=agent.id, company_id=cid, state="ready", started_at=t0, ended_at=t0 + timedelta(minutes=20), source="manual"),
            AgentStateHistory(user_id=agent.id, company_id=cid, state="on_call", started_at=t0 + timedelta(minutes=20), ended_at=t0 + timedelta(minutes=30), source="call")]
    db.add_all(hist); db.commit()

    client = TestClient(app)
    H = lambda u: {"Authorization": "Bearer " + create_access_token({"sub": u.email})}  # noqa: E731
    today = now.date().isoformat()
    q = f"date_from={today}&date_to={today}&queue_id={queue.id}"
    try:
        print("1. Reports (supervisor view)")
        r = client.get(f"/api/v1/contact-center/reports/inbound-by-queue?{q}", headers=H(admin)).json()
        row = r["rows"][0] if r["rows"] else {}
        check("RPT-02 offered / answered / abandoned", (row.get("offered"), row.get("answered"), row.get("abandoned")) == (4, 3, 1), row)
        check("RPT-02 service level 2 of 4 within 20s = 50%", row.get("service_level_pct") == 50.0, row.get("service_level_pct"))
        check("RPT-02 average speed of answer", row.get("avg_speed_of_answer_s") == 18.3, row.get("avg_speed_of_answer_s"))
        r = client.get(f"/api/v1/contact-center/reports/call-log?{q}", headers=H(admin)).json()
        check("RPT-01 call log rows", len(r["rows"]) == 4 and r["summary"]["answered"] == 3, r["summary"])
        r = client.get(f"/api/v1/contact-center/reports/missed-calls?{q}", headers=H(admin)).json()
        check("RPT-03 abandoned with loss reason", len(r["rows"]) == 1 and r["rows"][0]["loss_reason"] == "caller_hung_up_in_queue", r["rows"])
        r = client.get(f"/api/v1/contact-center/reports/missed-followup?date_from={today}&date_to={today}&agent_id={agent.id}", headers=H(admin)).json()
        check("RPT-04 follow-up per agent", any(x["assigned"] == 1 and x["attempts"] == 2 for x in r["rows"]), r["rows"])
        r = client.get(f"/api/v1/contact-center/reports/transfers?date_from={today}&date_to={today}&agent_id={agent.id}", headers=H(admin)).json()
        check("RPT-05 transfer listed", any(x["call_id"] == a1.id and x["to"] == "queue:Sales" for x in r["rows"]), r["rows"])
        r = client.get(f"/api/v1/contact-center/reports/agent-status?date_from={today}&date_to={today}&agent_id={agent.id}", headers=H(admin)).json()
        st = {x["status"]: x["seconds"] for x in r["rows"]}
        delta = {k: st.get(k, 0) - baseline.get(k, 0) for k in ("ready", "on_call")}
        check("RPT-07 time per status (20 min ready, 10 min on call added)", abs(delta["ready"] - 1200) <= 2 and abs(delta["on_call"] - 600) <= 2, delta)
        r = client.get(f"/api/v1/contact-center/reports/productivity?{q}", headers=H(admin)).json()
        prod = {x["agent"]: x for x in r["rows"]}
        mine = next((x for x in r["rows"] if x["inbound_calls"] == 2), None)
        check("RPT-08 agent handled 2 calls, avg talk 60s, hold 10s", mine and mine["avg_talk_s"] == 60 and mine["avg_hold_s"] == 10, prod)
        r = client.get(f"/api/v1/contact-center/reports/recording-access?date_from={today}&date_to={today}", headers=H(admin)).json()
        ops = sorted(x["operation"] for x in r["rows"] if x["call_id"] == a3.id)
        check("RPT-10 recording listen + download logged", ops == ["download", "listen"], ops)
        check("freshness + source shown", "generated_at" in r and r.get("source"), list(r.keys()))

        print("2. Scope + export permissions")
        if agent.id != admin.id:
            r = client.get(f"/api/v1/contact-center/reports/call-log?{q}", headers=H(agent)).json()
            check("agent only sees their own calls", r["rows"] and all(x["agent"] and x["id"] in (a1.id, a2.id) for x in r["rows"]), [x["id"] for x in r["rows"]])
            r = client.get(f"/api/v1/contact-center/reports/call-log?{q}&format=xlsx", headers=H(agent))
            check("agent without reports:export can't export", r.status_code == 403, r.status_code)
        r = client.get(f"/api/v1/contact-center/reports/call-log?{q}&format=xlsx", headers=H(admin))
        check("XLSX export", r.status_code == 200 and r.content[:2] == b"PK", r.status_code)
        r = client.get(f"/api/v1/contact-center/reports/call-log?{q}&format=csv", headers=H(admin))
        check("CSV export", r.status_code == 200 and r.text.startswith("id,started_at"), r.text[:40])
        r = client.get("/api/v1/audit-logs/export?action=report.exported", headers=H(admin))
        check("audit log CSV export (includes the report exports)", r.status_code == 200 and "report.exported" in r.text, r.status_code)

        print("3. Quality evaluation")
        form = QaForm(company_id=cid, name=f"__qa_{tag}", pass_score=70,
                      criteria=[{"key": "greeting", "label": "Greeting", "weight": 20}, {"key": "resolution", "label": "Resolution", "weight": 80}])
        db.add(form); db.commit(); extra.append(form)
        r = client.post("/api/v1/contact-center/qa/sample", headers=H(admin), json={"form_id": form.id, "agent_id": agent.id, "count": 5, "days": 1}).json()
        check("sample picks the agent's answered calls", r.get("created") == 2, r)
        ev = db.query(QaEvaluation).filter(QaEvaluation.form_id == form.id).first()
        r = client.put(f"/api/v1/contact-center/qa/evaluations/{ev.id}", headers=H(admin), json={"scores": {"greeting": 30, "resolution": 50}})
        check("score above the weight refused", r.status_code == 400, r.status_code)
        r = client.put(f"/api/v1/contact-center/qa/evaluations/{ev.id}", headers=H(admin),
                       json={"scores": {"greeting": 20, "resolution": 40}, "notes": "Good greeting", "improvement_plan": "Confirm resolution"}).json()
        check("score 60% -> not passed", r.get("total_score") == 60.0 and r.get("passed") is False, r)
        r = client.get(f"/api/v1/contact-center/reports/call-quality?date_from={today}&date_to={today}", headers=H(admin)).json()
        check("RPT-09 shows the evaluation", any(x["call_id"] == ev.call_id and x["score_pct"] == 60.0 for x in r["rows"]), r["rows"][:2])

        print("4. Retention")
        cc = get_settings(db, cid)
        saved = (cc.recording_retention_days, cc.call_history_retention_days, cc.chat_retention_days, cc.retention_changed_at)
        r = client.put("/api/v1/contact-center/settings", headers=H(admin), json={"recording_retention_days": 30})
        check("retention under 90 days refused", r.status_code == 400, r.status_code)
        r = client.put("/api/v1/contact-center/settings", headers=H(admin), json={"recording_retention_days": 90})
        db.refresh(cc)
        check("shortening starts the 7-day grace period", r.status_code == 200 and cc.retention_changed_at is not None, r.status_code)
        old = mk(9, answered=True, wait=5, handled_by=agent.id)
        old.started_at = now - timedelta(days=120)
        from app.core.object_storage import BUCKET_NAME, s3_client
        key = f"call-recordings/{cid}/test/{tag}.ogg"
        s3_client.put_object(Bucket=BUCKET_NAME, Key=key, Body=b"OggS-test")
        old.recording_object_key, old.recording_status = key, "completed"
        db.commit()
        res = qa_retention_service.purge_company(db, cc)
        check("nothing purged during grace", res["skipped"] == "grace period" and res["recordings"] == 0, res)
        res = qa_retention_service.purge_company(db, cc, now=datetime.now(timezone.utc) + timedelta(days=8))
        db.refresh(old)
        check("old recording purged after grace", res["recordings"] >= 1 and old.recording_status == "purged" and old.recording_object_key is None, res)
        try:
            s3_client.head_object(Bucket=BUCKET_NAME, Key=key)
            check("recording file removed from storage", False)
        except Exception:
            check("recording file removed from storage", True)
        db.refresh(a3)
        check("recent calls kept", a3.recording_status != "purged")
        cc.recording_retention_days, cc.call_history_retention_days, cc.chat_retention_days, cc.retention_changed_at = saved
        db.commit()
    finally:
        for c in calls:
            db.query(CallEvent).filter(CallEvent.call_id == c.id).delete()
            db.query(CallLeg).filter(CallLeg.call_id == c.id).delete()
            db.query(CallQueueEntry).filter(CallQueueEntry.voice_call_id == c.id).delete()
            db.query(MissedCallTask).filter(MissedCallTask.call_id == c.id).delete()
            db.query(QaEvaluation).filter(QaEvaluation.call_id == c.id).delete()
            db.delete(c)
        for h in hist:
            db.delete(h)
        for x in extra:
            db.delete(x)
        db.flush()
        db.delete(queue)
        db.query(AuditLog).filter(AuditLog.action.in_(("report.exported", "audit_log.exported", "retention.purged",
                                                       "contact_center.settings_updated")),
                                  AuditLog.created_at >= now - timedelta(minutes=5)).delete(synchronize_session=False)
        db.commit(); db.close()
    print("RESULT", "PASS" if not failures else f"FAIL ({', '.join(failures)})")
    return not failures


sys.exit(0 if main() else 1)
