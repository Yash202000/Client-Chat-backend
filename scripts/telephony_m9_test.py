"""
M9 test: wait time announcement (FR-CC-013) and recording pause (FR-CC-051).

1. Wait estimate: a queue with known waiting calls, agents and handled calls gives the expected
   position / minutes; the spoken text (en / ar); nothing when the queue doesn't announce.
2. Recording pause, for real: records a LiveKit room through Egress, pauses and resumes it through the
   API (permission + handler checks), ends the call, then checks both parts reach MinIO and the
   pause is in the call events and the audit log. Needs LiveKit, Egress, MinIO and the backend on
   :8000 (it receives the Egress webhooks). Removes what it created.

Run from backend/:  python -m scripts.telephony_m9_test [--company-id 1]
"""
import argparse
import asyncio
import sys
import time
import uuid
from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from livekit import api

from app.core.database import SessionLocal
from app.core.security import create_access_token
from app.models.audit_log import AuditLog
from app.models.call_event import CallEvent
from app.models.call_queue import CallQueueEntry
from app.models.contact_center import AgentState, CallQueue, CallQueueMember
from app.models.role import Role
from app.models.user import User
from app.models.voice_call import VoiceCall
from app.services import acd_service, call_service, livekit_sip_service, recording_service

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("--company-id", type=int, default=1)
args = parser.parse_args()
failures = []


def check(name, cond, detail=""):
    print(f"  {'ok  ' if cond else 'FAIL'} {name}{(' -> ' + str(detail)) if detail and not cond else ''}")
    if not cond:
        failures.append(name)


def wait_estimate_checks(db, cid, tag, cleanup):
    print("1. Wait time announcement")
    now = datetime.utcnow()
    queue = CallQueue(company_id=cid, name=f"__m9_{tag}", announce_wait_time=True, announce_interval_seconds=45)
    db.add(queue); db.flush()
    cleanup["queue"] = queue.id
    agents = []
    for i, state in enumerate(("ready", "on_call", "break")):  # break doesn't serve the queue
        u = User(email=f"m9_{tag}_{i}@test.local", hashed_password="x", is_active=True, company_id=cid)
        db.add(u); db.flush()
        db.add(AgentState(user_id=u.id, company_id=cid, state=state))
        db.add(CallQueueMember(queue_id=queue.id, user_id=u.id))
        agents.append(u.id)
    cleanup["users"] = agents
    calls = []
    for i in range(3):  # handled calls: 200 talk + 20 hold + 20 wrap-up = 240 s each
        c = VoiceCall(call_sid=f"M9H{i}_{tag}", provider="livekit_sip", room_name=f"m9h{i}_{tag}", from_number="+966500000000",
                      to_number="980", company_id=cid, status="completed", direction="inbound", queue_id=queue.id,
                      started_at=now - timedelta(hours=1), answered_at=now - timedelta(minutes=50),
                      ended_at=now - timedelta(minutes=46), talk_seconds=200, hold_seconds=20, wrap_up_seconds=20)
        db.add(c); calls.append(c)
    waiting = []
    for i, (prio, ago) in enumerate(((0, 30), (0, 20), (1, 5), (0, 10), (0, 2))):  # #3 urgent, joined later
        c = VoiceCall(call_sid=f"M9W{i}_{tag}", provider="livekit_sip", room_name=f"m9w{i}_{tag}", from_number="+966500000001",
                      to_number="980", company_id=cid, status="ringing", direction="inbound", queue_id=queue.id,
                      started_at=now - timedelta(seconds=ago))
        db.add(c); db.flush(); calls.append(c)
        db.add(CallQueueEntry(company_id=cid, call_sid=c.call_sid, source="m9test", caller_number=c.from_number,
                              status="waiting", priority=prio, queue_id=queue.id, voice_call_id=c.id,
                              entered_at=now - timedelta(seconds=ago), declined_user_ids=[]))
        waiting.append(c)
    cleanup["calls"] = [c.id for c in calls]
    db.commit()

    est = acd_service.wait_estimate(db, waiting[3].id)  # 2 normal before it + 1 urgent = position 4
    check("position counts earlier calls and higher priority", est and est["position"] == 4, est)
    check("average handling time from the queue's calls (240 s)", est and est["average_handle_seconds"] == 240, est)
    check("agents serving = ready + on call (not on break)", est and est["agents"] == 2, est)
    check("expected wait = 4 x 240 s / 2 agents = 8 min", est and est["minutes"] == 8, est)
    check("repeat interval from the queue", est and est["interval"] == 45, est)
    first = acd_service.wait_estimate(db, waiting[2].id)
    check("urgent call is first in line", first and first["position"] == 1 and first["minutes"] == 2, first)
    text = acd_service.wait_message(est, "en")
    check("English announcement", "number 4" in text and "8 minutes" in text, text)
    check("Arabic announcement", "4" in acd_service.wait_message(est, "ar") and "دقائق" in acd_service.wait_message(est, "ar"))
    check("one minute wording", "about one minute" in acd_service.wait_message({"position": 1, "minutes": 1}))
    queue.announce_wait_time = False; db.commit()
    check("no announcement when the queue has it off", acd_service.wait_estimate(db, waiting[3].id) is None)
    queue.announce_wait_time = True
    for a in db.query(AgentState).filter(AgentState.user_id.in_(agents)).all():
        a.state = "break"
    db.commit()
    est0 = acd_service.wait_estimate(db, waiting[3].id)
    check("no agents serving: estimate still given (4 x 240 s)", est0 and est0["minutes"] == 16, est0)
    check("calls not waiting in a queue get no estimate", acd_service.wait_estimate(db, calls[0].id) is None)


async def fake_caller(room_name: str, stop: asyncio.Event) -> None:
    """Egress only starts once the room has audio: join as a 'caller' playing a 440 Hz tone."""
    import math
    from livekit import rtc
    from app.core.config import settings

    token = (api.AccessToken(settings.LIVEKIT_API_KEY, settings.LIVEKIT_API_SECRET).with_identity("m9-caller")
             .with_grants(api.VideoGrants(room_join=True, room=room_name)).to_jwt())
    room = rtc.Room()
    await room.connect(settings.LIVEKIT_URL, token)
    source = rtc.AudioSource(48000, 1)
    track = rtc.LocalAudioTrack.create_audio_track("tone", source)
    await room.local_participant.publish_track(track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE))
    n, samples = 0, 480  # 10 ms frames
    while not stop.is_set():
        frame = rtc.AudioFrame.create(48000, 1, samples)
        data = frame.data
        for i in range(samples):
            data[i] = int(8000 * math.sin(2 * math.pi * 440 * (n + i) / 48000))
        n += samples
        await source.capture_frame(frame)
    await room.disconnect()


async def recording_checks(db, cid, tag, cleanup):
    print("2. Recording pause / resume (LiveKit Egress -> MinIO)")
    from app.core.object_storage import BUCKET_NAME, s3_client
    from app.main import app

    admin = (db.query(User).join(Role, User.role_id == Role.id)
             .filter(User.company_id == cid, Role.name == "Admin", User.is_active.is_(True)).order_by(User.id).first())
    role = Role(name=f"__m9_{tag}", description="m9 test", company_id=cid)
    db.add(role); db.flush()
    nobody = User(email=f"m9_{tag}_np@test.local", hashed_password="x", is_active=True, company_id=cid, role_id=role.id)
    db.add(nobody); db.commit()
    cleanup["role"], cleanup["users"] = role.id, cleanup.get("users", []) + [nobody.id]

    room = f"m9rec_{tag}"
    lk = livekit_sip_service._api()
    try:
        await lk.room.create_room(api.CreateRoomRequest(name=room, empty_timeout=120))
    finally:
        await lk.aclose()
    now = datetime.utcnow()
    call = VoiceCall(call_sid=f"M9R_{tag}", provider="livekit_sip", room_name=room, from_number="+966500000002", to_number="980",
                     company_id=cid, status="in_progress", direction="inbound", started_at=now, answered_at=now,
                     handled_by_user_id=admin.id)
    db.add(call); db.commit()
    cleanup["calls"] = cleanup.get("calls", []) + [call.id]
    stop = asyncio.Event()
    caller = asyncio.create_task(fake_caller(room, stop))
    await asyncio.sleep(2)

    await recording_service.start(db, call)
    check("recording started (part 1)", call.recording_status == "recording" and len(call.recording_parts) == 1, call.recording_status)
    await asyncio.sleep(5)
    H = lambda u: {"Authorization": "Bearer " + create_access_token({"sub": u.email})}  # noqa: E731
    base = f"/api/v1/telephony/calls/{call.id}/recording"
    with TestClient(app) as client:
        r = client.post(f"{base}/pause", json={"reason": "card details"}, headers=H(nobody))
        check("pause without recordings:pause -> 403", r.status_code == 403, r.status_code)
        r = client.post(f"{base}/pause", json={"reason": "card details"}, headers=H(admin))
        check("agent on the call pauses", r.status_code == 200 and r.json().get("recording_status") == "paused", r.text[:200])
        r = client.post(f"{base}/pause", json={}, headers=H(admin))
        check("pausing twice is refused", r.status_code == 400, r.status_code)
        await asyncio.sleep(4)
        r = client.post(f"{base}/resume", json={}, headers=H(admin))
        check("agent resumes (part 2)", r.status_code == 200 and r.json().get("recording_status") == "recording", r.text[:200])
    await asyncio.sleep(5)
    db.expire_all()
    call = db.query(VoiceCall).get(call.id)
    check("two parts with different files", len(call.recording_parts) == 2 and
          call.recording_parts[0]["key"] != call.recording_parts[1]["key"], call.recording_parts)

    call_service.finish_call(db, call, "agent", actor_user_id=admin.id)
    stop.set()
    await caller
    lk = livekit_sip_service._api()
    try:
        await lk.room.delete_room(api.DeleteRoomRequest(room=room))
    finally:
        await lk.aclose()
    deadline = time.time() + 60
    while time.time() < deadline:
        db.expire_all()
        call = db.query(VoiceCall).get(call.id)
        if call.recording_status in ("completed", "failed") and all(p.get("status") in ("completed", "failed") for p in call.recording_parts):
            break
        await asyncio.sleep(2)
    parts = call.recording_parts
    check("both parts completed (Egress webhooks)", [p.get("status") for p in parts] == ["completed", "completed"], parts)
    check("recording completed", call.recording_status == "completed", call.recording_status)
    stored = []
    for p in parts:
        try:
            s3_client.head_object(Bucket=BUCKET_NAME, Key=p["key"]); stored.append(p["key"])
        except Exception:
            pass
    check("both parts are in MinIO", len(stored) == 2, stored)
    check("duration = sum of parts (pause not recorded)",
          call.recording_duration_secs and abs(call.recording_duration_secs - sum(p.get("duration") or 0 for p in parts)) < 0.5,
          call.recording_duration_secs)
    check("download/listen returns one link per part", len(recording_service.part_keys(call)) == 2)
    types = [e.type for e in db.query(CallEvent).filter(CallEvent.call_id == call.id).order_by(CallEvent.id).all()]
    check("pause and resume are call events", "recording_paused" in types and "recording_resumed" in types, types)
    acts = {a for (a,) in db.query(AuditLog.action).filter(AuditLog.entity_type == "voice_call", AuditLog.entity_id == call.id)}
    check("pause and resume are audited", {"recording.paused", "recording.resumed"} <= acts, acts)
    cleanup["keys"] = [p["key"] for p in parts if p.get("key")]


async def main() -> bool:
    db = SessionLocal()
    cid, tag = args.company_id, uuid.uuid4().hex[:6]
    cleanup = {}
    try:
        wait_estimate_checks(db, cid, tag, cleanup)
        await recording_checks(db, cid, tag, cleanup)
    finally:
        db.rollback()
        from app.core.object_storage import BUCKET_NAME, s3_client
        for key in cleanup.get("keys", []):
            try:
                s3_client.delete_object(Bucket=BUCKET_NAME, Key=key)
            except Exception:
                pass
        ids = cleanup.get("calls", [])
        if ids:
            from app.models.contact_center import MissedCallTask
            from app.models.call_event import CallLeg
            db.query(CallQueueEntry).filter(CallQueueEntry.voice_call_id.in_(ids)).delete(synchronize_session=False)
            db.query(MissedCallTask).filter(MissedCallTask.call_id.in_(ids)).delete(synchronize_session=False)
            db.query(CallLeg).filter(CallLeg.call_id.in_(ids)).delete(synchronize_session=False)
            db.query(CallEvent).filter(CallEvent.call_id.in_(ids)).delete(synchronize_session=False)
            db.query(VoiceCall).filter(VoiceCall.id.in_(ids)).delete(synchronize_session=False)
        users = cleanup.get("users", [])
        if users:
            db.query(AgentState).filter(AgentState.user_id.in_(users)).delete(synchronize_session=False)
            db.query(CallQueueMember).filter(CallQueueMember.user_id.in_(users)).delete(synchronize_session=False)
        if cleanup.get("queue"):
            db.query(CallQueue).filter(CallQueue.id == cleanup["queue"]).delete(synchronize_session=False)
        if users:
            from app.models.contact_center import AgentStateHistory
            db.query(AgentStateHistory).filter(AgentStateHistory.user_id.in_(users)).delete(synchronize_session=False)
            db.query(User).filter(User.id.in_(users)).delete(synchronize_session=False)
        if cleanup.get("role"):
            db.query(Role).filter(Role.id == cleanup["role"]).delete(synchronize_session=False)
        db.commit(); db.close()
    print("RESULT", "PASS" if not failures else f"FAIL ({', '.join(failures)})")
    return not failures


sys.exit(0 if asyncio.run(main()) else 1)
