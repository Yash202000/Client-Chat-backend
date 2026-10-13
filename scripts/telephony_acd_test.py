"""
Integration test for contact-centre queues (ACD), agent states, hold, wrap-up and CTI-down records.
No audio or LiveKit call needed; uses the dev database and removes everything it creates.

Run from backend/:  python -m scripts.telephony_acd_test [--company-id 1]
"""
import argparse
import asyncio
import sys
import time
import uuid
from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.core.security import create_access_token
from app.models.call_event import CallEvent
from app.models.call_queue import CallQueueEntry
from app.models.contact_center import (
    AgentReasonCode, AgentState, AgentStateHistory, CallQueue, CallQueueMember, DispositionCode, Shift, ShiftAssignment,
)
from app.models.conversation_session import ConversationSession
from app.models.role import Role
from app.models.user import User
from app.models.voice_call import VoiceCall
from app.services import acd_service, call_service

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--company-id", type=int, default=1)
args = parser.parse_args()
failures = []


def check(name, cond, detail=""):
    print(f"  {'ok  ' if cond else 'FAIL'} {name}{(' -> ' + str(detail)) if detail and not cond else ''}")
    if not cond:
        failures.append(name)


async def main():
    db = SessionLocal()
    tag = uuid.uuid4().hex[:6]
    cid = args.company_id
    users = (db.query(User).join(Role, User.role_id == Role.id)
             .filter(User.company_id == cid, User.is_active.is_(True), User.is_super_admin.is_(False))
             .order_by(User.id).limit(2).all())
    if len(users) < 2:
        print("needs two active users in the company"); return False
    a, b = users
    saved = {u.id: (u.presence_status, db.query(AgentState).filter(AgentState.user_id == u.id).first()) for u in users}
    had_state = {uid: st is not None for uid, (_, st) in saved.items()}
    for u in users:
        u.presence_status = "online"
    db.commit()

    queue = CallQueue(company_id=cid, name=f"__acd_test_{tag}", offer_timeout_seconds=20, wrap_up_seconds=30,
                      max_wait_seconds=120, overflow_text="Please call again.")
    queue.members = [CallQueueMember(user_id=a.id), CallQueueMember(user_id=b.id)]
    reason = AgentReasonCode(company_id=cid, name=f"__lunch_{tag}", state="break")
    dispo = DispositionCode(company_id=cid, name=f"__complaint_{tag}", requires_note=True)
    db.add_all([queue, reason, dispo]); db.commit()
    created_calls, shift = [], None
    try:
        print("1. Agent states")
        for u in users:
            acd_service.set_state(db, u.id, cid, "ready", source="system")
        # make A the longest idle
        acd_service.get_state(db, a.id, cid).last_call_ended_at = datetime.utcnow() - timedelta(hours=2)
        acd_service.get_state(db, b.id, cid).last_call_ended_at = datetime.utcnow() - timedelta(minutes=5)
        db.commit()
        try:
            acd_service.set_state(db, a.id, cid, "break", changed_by=a.id)
            check("not-ready needs a reason", False)
        except acd_service.StateError:
            check("not-ready needs a reason", True)
        try:
            acd_service.set_state(db, a.id, cid, "on_call", changed_by=a.id)
            check("on_call can't be set by hand", False)
        except acd_service.StateError:
            check("on_call can't be set by hand", True)
        row = acd_service.set_state(db, a.id, cid, "break", reason_code_id=reason.id, changed_by=a.id)
        check("break with a reason", row.state == "break" and row.reason_code_id == reason.id, acd_service.serialize_state(row))
        check("break agent not eligible", a.id not in acd_service.eligible_agents(db, queue, []))
        acd_service.set_state(db, a.id, cid, "ready", changed_by=a.id)

        print("2. Queue + offers (longest idle first, timeout moves on)")
        conv = ConversationSession(conversation_id=f"voice_acd_{tag}", company_id=cid, channel="voice",
                                   status="pending_agent_assignment", waiting_for_agent=True, is_ai_enabled=False)
        db.add(conv)
        call = VoiceCall(call_sid=f"ACD_{tag}", provider="livekit_sip", room_name=f"call_acd_{tag}",
                         from_number="+966500000003", to_number="980", company_id=cid,
                         conversation_id=conv.conversation_id, status="in_progress", direction="inbound",
                         started_at=datetime.utcnow(), answered_at=datetime.utcnow())
        db.add(call); db.commit(); created_calls.append(call)
        routed = await call_service.route_to_agents(db, call, None, queue_id=queue.id)
        check("routed to the queue with overflow settings", routed.get("queued") and routed["overflow_text"] == "Please call again.", routed)
        entry = db.query(CallQueueEntry).filter(CallQueueEntry.voice_call_id == call.id).one()
        check("offered to the longest-idle agent", entry.offered_to_user_id == a.id, entry.offered_to_user_id)
        entry.offer_expires_at = datetime.utcnow() - timedelta(seconds=1); db.commit()
        await acd_service.dispatch(db, cid)
        db.refresh(entry)
        check("unanswered offer moves to the next agent", entry.offered_to_user_id == b.id and a.id in entry.declined_user_ids,
              (entry.offered_to_user_id, entry.declined_user_ids))

        print("3. Accept -> on call -> hold -> end -> wrap-up")
        claimed = call_service.claim_call(db, call.id, cid, b.id)
        check("offered agent can take it", claimed is not None)
        await acd_service.on_accepted(db, claimed, b.id)
        db.refresh(entry)
        check("queue entry connected", entry.status == "connected" and entry.assigned_agent_id == b.id, entry.status)
        check("agent on call", acd_service.get_state(db, b.id, cid).state == "on_call")
        call_service.set_hold(db, claimed, True, b.id)
        time.sleep(1.2)
        call_service.set_hold(db, claimed, False, b.id)
        db.refresh(claimed)
        check("hold time tracked", (claimed.hold_seconds or 0) >= 1.0, claimed.hold_seconds)
        await call_service.end_call(db, claimed, ended_by="agent", actor_user_id=b.id, hang_up=False)
        db.refresh(claimed)
        check("talk time excludes hold", claimed.talk_seconds is not None and claimed.talk_seconds < claimed.duration_seconds,
              (claimed.talk_seconds, claimed.duration_seconds, claimed.hold_seconds))
        check("agent in wrap-up", acd_service.get_state(db, b.id, cid).state == "wrap_up")
        try:
            await acd_service.complete_wrap_up(db, claimed, b.id, dispo.id, "")
            check("disposition note enforced", False)
        except acd_service.StateError:
            check("disposition note enforced", True)
        row = await acd_service.complete_wrap_up(db, claimed, b.id, dispo.id, "Caller reported an issue")
        db.refresh(claimed)
        check("wrap-up saved, agent ready", row.state == "ready" and claimed.disposition_code_id == dispo.id
              and claimed.wrap_up_seconds is not None, (row.state, claimed.disposition_code_id))
        events = [e.type for e in db.query(CallEvent).filter(CallEvent.call_id == claimed.id).order_by(CallEvent.seq)]
        check("event trail", events[:3] == ["queue", "offer", "offer_timeout"] and {"accept", "hold", "resume", "end", "wrap_up"} <= set(events), events)

        print("4. Shifts")
        shift = Shift(company_id=cid, name=f"__night_{tag}", timezone="UTC", schedule=[])
        db.add(shift); db.flush()
        db.add(ShiftAssignment(shift_id=shift.id, user_id=a.id)); db.commit()
        check("agent outside their shift is not offered calls", a.id not in acd_service.eligible_agents(db, queue, []))
        shift.schedule = [{"days": list(range(7)), "start": "00:00", "end": "24:00"}]; db.commit()
        check("agent on shift is eligible", a.id in acd_service.eligible_agents(db, queue, []))

        print("5. API: my state + wrap-up permissions, CTI-down manual record + reconcile")
        from app.main import app
        client = TestClient(app)
        hdr = {"Authorization": "Bearer " + create_access_token({"sub": a.email})}
        r = client.put("/api/v1/contact-center/me/state", headers=hdr, json={"state": "break"})
        check("API rejects break without reason", r.status_code == 400, r.status_code)
        r = client.put("/api/v1/contact-center/me/state", headers=hdr, json={"state": "break", "reason_code_id": reason.id})
        check("API sets break with reason", r.status_code == 200 and r.json()["agent"]["state"] == "break", r.text)
        r = client.get("/api/v1/contact-center/me/state", headers=hdr)
        check("API lists reason codes", any(c["id"] == reason.id for c in r.json().get("reason_codes", [])), r.text[:200])
        r = client.post(f"/api/v1/telephony/calls/{claimed.id}/wrap-up", headers=hdr, json={})
        check("only the handling agent can wrap up", r.status_code == 403, r.status_code)
        r = client.post("/api/v1/telephony/calls/manual", headers=hdr,
                        json={"caller": "+966500000003", "note": "CTI was down",
                              "occurred_at": (claimed.started_at + timedelta(minutes=2)).isoformat()})
        manual_id = r.json()["call"]["id"] if r.status_code == 200 else None
        check("manual call recorded", r.status_code == 200 and r.json()["call"]["manual_entry"], r.text[:200])
        admin_hdr = {"Authorization": "Bearer " + create_access_token({"sub": a.email})}
        r = client.post("/api/v1/telephony/calls/reconcile", headers=admin_hdr)
        matched = r.json().get("matched", []) if r.status_code == 200 else []
        check("manual record reconciled with the real call", any(m["manual_call_id"] == manual_id and m["call_id"] == claimed.id for m in matched),
              (r.status_code, r.text[:200]))
        if manual_id:
            created_calls.append(db.query(VoiceCall).filter(VoiceCall.id == manual_id).one())
        print("6. Transfer rules")
        from app.models.contact_center import DirectoryEntry
        from app.services import transfer_service
        hotline = DirectoryEntry(company_id=cid, name="__Hotline 19991", number="19991", kind="entity", transfer_allowed=False)
        db.add(hotline); db.commit()
        conv2 = ConversationSession(conversation_id=f"voice_acd2_{tag}", company_id=cid, channel="voice", status="assigned",
                                    assignee_id=a.id, is_ai_enabled=False)
        db.add(conv2)
        call2 = VoiceCall(call_sid=f"ACD2_{tag}", provider="livekit_sip", room_name=f"call_acd2_{tag}", from_number="+966500000004",
                          to_number="980", company_id=cid, conversation_id=conv2.conversation_id, status="in_progress",
                          direction="inbound", started_at=datetime.utcnow(), answered_at=datetime.utcnow(), handled_by_user_id=a.id)
        db.add(call2); db.commit(); created_calls.append(call2)
        acd_service.set_state(db, a.id, cid, "on_call", source="call", call_id=call2.id)
        for label, kwargs, user in [
            ("19991 is never transferable", {"target_type": "external", "number": "19991"}, a),
            ("unknown external number refused", {"target_type": "external", "number": "+15550000000"}, a),
            ("only the handling agent can transfer", {"target_type": "agent", "target_id": a.id}, b),
        ]:
            try:
                await transfer_service.blind_transfer(db, call2, user, **kwargs)
                check(label, False)
            except transfer_service.TransferError as e:
                check(label, True, str(e))
        queue.is_open = False; db.commit()
        try:
            await transfer_service.blind_transfer(db, call2, a, target_type="queue", target_id=queue.id)
            check("closed queue refuses transfers", False)
        except transfer_service.TransferError:
            check("closed queue refuses transfers", True)
        queue.is_open = True; db.commit()
        # agent transfer that isn't answered falls back (no queue on this call -> back to the transferring agent)
        await transfer_service.blind_transfer(db, call2, a, target_type="agent", target_id=b.id, note="test note")
        e2 = db.query(CallQueueEntry).filter(CallQueueEntry.voice_call_id == call2.id, CallQueueEntry.status == "waiting").one()
        check("transfer offered to the target agent", e2.offered_to_user_id == b.id, e2.offered_to_user_id)
        check("transferring agent released (wrap-up)", acd_service.get_state(db, a.id, cid).state == "wrap_up")
        e2.offer_expires_at = datetime.utcnow() - timedelta(seconds=1); db.commit()
        await acd_service.dispatch(db, cid)
        db.refresh(e2)
        check("unanswered transfer returns to the transferring agent", e2.offered_to_user_id == a.id, e2.offered_to_user_id)
        evs = [e.type for e in db.query(CallEvent).filter(CallEvent.call_id == call2.id).order_by(CallEvent.seq)]
        check("transfer + transfer_failed recorded", "transfer" in evs and "transfer_failed" in evs, evs)
        db.delete(hotline); db.commit()

        print("7. Missed / abandoned calls, numbers, tasks")
        from app.models.contact_center import BlockedNumber, MissedCallTask
        from app.services import missed_call_service, outbound_service
        cc = outbound_service.get_settings(db, cid)
        saved_cc = (cc.abandon_threshold_seconds, cc.create_callback_tasks, list(cc.allowed_country_codes or []))
        cc.abandon_threshold_seconds, cc.create_callback_tasks, cc.allowed_country_codes = 5, True, ["+966"]
        db.commit()
        n = lambda raw: outbound_service.normalize_number(raw, cc)  # noqa: E731
        check("0501234567 -> +966501234567", n("050 123 4567") == "+966501234567", n("050 123 4567"))
        check("501234567 -> +966501234567", n("501234567") == "+966501234567")
        check("00966... -> +966...", n("00966501234567") == "+966501234567")
        for bad in ("+15551234567", "12ab"):
            try:
                n(bad); check(f"{bad} refused", False)
            except outbound_service.OutboundError:
                check(f"{bad} refused", True)
        blk = BlockedNumber(company_id=cid, number="+966500000099", scope="outbound", reason="test")
        db.add(blk); db.commit()
        try:
            outbound_service.check_can_call(db, cid, "+966500000099"); check("blocked number refused", False)
        except outbound_service.OutboundError:
            check("blocked number refused", True)
        db.delete(blk); db.commit()

        def missed_call(suffix, ended_by, wait):
            conv_m = ConversationSession(conversation_id=f"voice_m{suffix}_{tag}", company_id=cid, channel="voice",
                                         status="pending_agent_assignment", is_ai_enabled=False)
            db.add(conv_m)
            start = datetime.utcnow() - timedelta(seconds=wait)
            c = VoiceCall(call_sid=f"M{suffix}_{tag}", provider="livekit_sip", room_name=f"call_m{suffix}_{tag}",
                          from_number="+966500000005", to_number="980", company_id=cid, conversation_id=conv_m.conversation_id,
                          status="ringing", direction="inbound", started_at=start, queue_id=queue.id)
            db.add(c); db.commit(); created_calls.append(c)
            db.add(CallQueueEntry(company_id=cid, call_sid=c.call_sid, source="livekit_sip", caller_number=c.from_number,
                                  session_id=conv_m.conversation_id, status="waiting", queue_id=queue.id, voice_call_id=c.id,
                                  entered_at=start, declined_user_ids=[])); db.commit()
            call_service.finish_call(db, c, ended_by)
            db.refresh(c)
            return c, db.query(MissedCallTask).filter(MissedCallTask.call_id == c.id).first()

        c1, t1 = missed_call("ab", "caller", 30)
        check("caller hung up after 30s in queue -> abandoned task", c1.missed_classification == "abandoned" and t1 is not None, c1.missed_classification)
        c2, t2 = missed_call("sh", "caller", 2)
        check("hung up within threshold -> short abandon, no task", c2.missed_classification == "short_abandon" and t2 is None, c2.missed_classification)
        c3, t3 = missed_call("ms", "system", 60)
        check("nobody answered -> missed task", c3.missed_classification == "missed" and t3 is not None and t3.loss_reason == "no_agent_answered",
              (c3.missed_classification, t3 and t3.loss_reason))
        missed_call_service.assign(db, t1, b.id, a.id)
        check("supervisor assigns task", t1.status == "assigned" and t1.assigned_to_user_id == b.id)
        try:
            missed_call_service.close(db, t1, b.id, "refused", ""); check("refusal needs a comment", False)
        except missed_call_service.TaskError:
            check("refusal needs a comment", True)
        missed_call_service.close(db, t1, b.id, "refused", "Caller did not want to talk")
        check("task closed with result", t1.status == "closed" and t1.result == "refused")
        wl = {w["user_id"]: w for w in missed_call_service.workload(db, cid)}
        check("workload shows completed task for agent", wl.get(b.id, {}).get("completed") == 1, wl)
        cc.abandon_threshold_seconds, cc.create_callback_tasks, cc.allowed_country_codes = saved_cc
        db.commit()
    finally:
        from app.models.audit_log import AuditLog
        from app.models.chat_message import ChatMessage
        for c in created_calls:
            db.refresh(c)
            db.query(CallEvent).filter(CallEvent.call_id == c.id).delete()
            db.query(CallQueueEntry).filter(CallQueueEntry.voice_call_id == c.id).delete()
            from app.models.contact_center import MissedCallTask as _MT
            for _t in db.query(_MT).filter(_MT.call_id == c.id).all():
                db.query(AuditLog).filter(AuditLog.entity_type == "missed_call_task", AuditLog.entity_id == _t.id).delete()
            db.query(_MT).filter(_MT.call_id == c.id).delete()
            db.query(AuditLog).filter(AuditLog.entity_type == "voice_call", AuditLog.entity_id == c.id).delete()
            from app.models.chat_message import ChatMessage as _CM
            from app.models.call_event import CallLeg as _CL
            db.query(_CL).filter(_CL.call_id == c.id).delete()
        for c in created_calls:
            conv_id = c.conversation_id
            db.query(AgentState).filter(AgentState.current_call_id == c.id).update({"current_call_id": None})
            db.delete(c); db.flush()
            s = db.query(ConversationSession).filter(ConversationSession.conversation_id == conv_id).first()
            if s:
                db.query(ChatMessage).filter(ChatMessage.session_id == s.id).delete()
                db.delete(s)
        if shift:
            db.delete(shift)
        db.query(AgentStateHistory).filter(AgentStateHistory.reason_code_id == reason.id).update({"reason_code_id": None})
        db.query(AgentState).filter(AgentState.reason_code_id == reason.id).update({"reason_code_id": None})
        db.delete(queue); db.delete(reason); db.delete(dispo)
        for u in users:
            u.presence_status = saved[u.id][0]
            if not had_state[u.id]:
                db.query(AgentStateHistory).filter(AgentStateHistory.user_id == u.id).delete()
                db.query(AgentState).filter(AgentState.user_id == u.id).delete()
        db.commit(); db.close()
    print("RESULT", "PASS" if not failures else f"FAIL ({', '.join(failures)})")
    return not failures


sys.exit(0 if asyncio.run(main()) else 1)
