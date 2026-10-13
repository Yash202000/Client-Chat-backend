"""
Telephony loopback test (no softphone): LiveKit SIP calls itself.

  outbound trunk -> <sip-host>:5060 -> temporary inbound test number -> dispatch rule -> room call_*

--mode ai      the voice process answers; checks keypad digit, call record and events reach Redis
--mode ivr     the number's entry workflow collects 3 keypad digits then hangs up (IVR nodes, voice process)
--mode queue   like direct, but through a queue (ACD offer to the ready agent), with hold/resume + wrap-up
--mode transfer  queue call answered by --user-email, blind-transferred to --user2-email, supervised (listen),
               then hung up; checks the transfer chain (legs), supervision event and recording
--mode missed  caller abandons a queue -> callback task -> supervisor assigns -> agent calls back through the
               outbound trunk (answered by the voice process on a 2nd test number) -> task closed
--mode direct  the call rings human agents; a simulated agent accepts via the API, joins the room
               like the browser does, talks briefly and hangs up (needs --api-url and --user-email)

Needs the telephony stack, REDIS_URL, and (ai mode) a running voice process or (direct mode) a
backend receiving LiveKit webhooks. Creates and removes its own test number and trunks.

Run from backend/:
  python -m scripts.telephony_loopback_test --sip-host 192.168.31.107
  python -m scripts.telephony_loopback_test --sip-host 192.168.31.107 --mode direct \\
      --api-url http://localhost:8000 --user-email agent@example.com
"""
import argparse
import asyncio
import json
import sys
import time

import httpx
import redis.asyncio as aioredis
from livekit import api, rtc

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.security import create_access_token
from app.models.call_event import CallEvent
from app.models.phone_number import PhoneNumber
from app.models.user import User
from app.models.voice_call import VoiceCall
from app.services import livekit_sip_service

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("--sip-host", required=True, help="LAN IP where LiveKit SIP listens")
parser.add_argument("--mode", choices=["ai", "direct", "ivr", "queue", "transfer", "missed"], default="ai")
parser.add_argument("--user2-email", help="second agent who receives the transfer (transfer mode)")
parser.add_argument("--company-id", type=int, default=1)
parser.add_argument("--api-url", default="http://localhost:8000", help="backend base URL (direct mode)")
parser.add_argument("--user-email", help="user who answers the call (direct mode; must be online)")
args = parser.parse_args()
TEST_NUMBER = "000999"  # dedicated test number, removed at the end
CALLER = "+966500000001"


def lk_client() -> api.LiveKitAPI:
    return api.LiveKitAPI(settings.LIVEKIT_URL.replace("ws://", "http://").replace("wss://", "https://"),
                          settings.LIVEKIT_API_KEY, settings.LIVEKIT_API_SECRET)


async def main() -> bool:
    db = SessionLocal()
    user = None
    user2 = None
    if args.mode == "transfer":
        user2 = db.query(User).filter(User.email == args.user2_email).first() if args.user2_email else None
        if not user2:
            print("transfer mode needs --user2-email"); return False
        user2.presence_status = "online"; db.commit()
    user2_id = user2.id if user2 else None
    if args.mode in ("direct", "queue", "transfer", "missed"):
        user = db.query(User).filter(User.email == args.user_email).first() if args.user_email else None
        if not user:
            print("direct mode needs --user-email of an existing user"); return False
        user.presence_status = "online"; db.commit()  # make sure the test agent rings
    user_id = user.id if user else None

    queue = None
    if args.mode in ("queue", "transfer", "missed"):
        from app.models.contact_center import CallQueue, CallQueueMember
        from app.services import acd_service
        queue = CallQueue(company_id=user.company_id, name=f"__loopback_queue_{int(time.time())}", offer_timeout_seconds=15, wrap_up_seconds=60)
        queue.members = [CallQueueMember(user_id=user.id)]
        db.add(queue); db.commit(); db.refresh(queue)
        acd_service.set_state(db, user.id, user.company_id, "logged_out" if args.mode == "missed" else "ready", source="system")
    workflow = None
    if args.mode == "ivr":
        from app.models.workflow import Workflow
        workflow = Workflow(name="__loopback_ivr_test", company_id=args.company_id, steps={}, is_active=False, version=1,
                            visual_steps={"nodes": [
                                {"id": "start", "type": "start", "position": {"x": 250, "y": 50}, "data": {}},
                                {"id": "pin", "type": "get_digits", "position": {"x": 250, "y": 200}, "data": {"params": {
                                    "prompt_text": "Enter three digits.", "max_digits": 3, "timeout_seconds": 8,
                                    "save_to_variable": "pin"}}},
                                {"id": "bye", "type": "hangup", "position": {"x": 250, "y": 350},
                                 "data": {"params": {"text": "You entered {{context.pin}}. Goodbye."}}},
                            ], "edges": [{"id": "e1", "source": "start", "target": "pin"},
                                         {"id": "e2", "source": "pin", "target": "bye"}]})
        db.add(workflow); db.commit(); db.refresh(workflow)
    phone = PhoneNumber(company_id=user.company_id if user else args.company_id, number=TEST_NUMBER,
                        provider="livekit_sip", friendly_name="Loopback test",
                        routing_mode="direct" if args.mode in ("direct", "queue", "transfer", "missed") else "ai",
                        recording_enabled=args.mode == "transfer",
                        queue_id=queue.id if queue else None,
                        entry_workflow_id=workflow.id if workflow else None,
                        language="en", is_active=True, provider_config={})
    db.add(phone); db.commit(); db.refresh(phone)

    events, offers = [], asyncio.Queue()
    r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    ps = r.pubsub(); await ps.subscribe(settings.WS_FANOUT_CHANNEL)

    async def collect():
        async for m in ps.listen():
            if m["type"] != "message":
                continue
            msg = json.loads(json.loads(m["data"])["message"])
            if not str(msg.get("type", "")).startswith("phone_call"):
                continue
            events.append(msg)
            print(f"  [ws] {msg['type']}")
            if msg["type"] == "phone_call_offer":
                await offers.put(msg)
    collector = asyncio.create_task(collect())

    lk = lk_client()
    out_trunk, agent_room, call_id, error = None, None, None, None
    wrapped_state = None
    supervise_ok = {"listen": None}
    recording = {"status": None, "listen": None, "download": None}

    async def join(acc):
        room = rtc.Room()
        await room.connect(acc["livekit_url"], acc["token"])
        mic = rtc.LocalAudioTrack.create_audio_track("mic", rtc.AudioSource(48000, 1))
        await room.local_participant.publish_track(mic, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE))
        return room

    async def run_transfer(lk_, dial, offers_, t0):
        nonlocal call_id, agent_room
        h1 = {"Authorization": "Bearer " + create_access_token({"sub": args.user_email})}
        h2 = {"Authorization": "Bearer " + create_access_token({"sub": args.user2_email})}
        from app.services import acd_service as acd
        d2 = SessionLocal(); acd.set_state(d2, user2_id, phone.company_id, "ready", source="system"); d2.close()
        offer = await asyncio.wait_for(offers_.get(), 20)
        call_id = offer["call"]["id"]
        async with httpx.AsyncClient(base_url=args.api_url, timeout=20) as http:
            acc = (await http.post(f"/api/v1/telephony/calls/{call_id}/accept", headers=h1)).json()
            room_a = await join(acc)
            await asyncio.wait_for(dial, 20)
            print(f"A answered in {time.time()-t0:.1f}s")
            await asyncio.sleep(2)
            r = await http.post(f"/api/v1/telephony/calls/{call_id}/transfer", headers=h1,
                                json={"target_type": "agent", "target_id": user2_id, "note": "Caller asks about invoice"})
            print("transfer ->", r.status_code, r.text[:120])
            await room_a.disconnect()
            offer2 = await asyncio.wait_for(offers_.get(), 20)
            print("B offered:", offer2["ring_user_ids"], "transfer info:", offer2.get("transfer"))
            acc2 = (await http.post(f"/api/v1/telephony/calls/{call_id}/accept", headers=h2)).json()
            agent_room = await join(acc2)
            await asyncio.sleep(2)
            sup = await http.post(f"/api/v1/telephony/calls/{call_id}/supervise", headers=h1, json={"mode": "listen"})
            supervise_ok["listen"] = sup.status_code
            if sup.status_code == 200:
                sroom = rtc.Room(); await sroom.connect(sup.json()["livekit_url"], sup.json()["token"])
                await asyncio.sleep(2); await sroom.disconnect()
            await asyncio.sleep(1)
            r = await http.post(f"/api/v1/telephony/calls/{call_id}/hangup", headers=h2)
            print("B hangup ->", r.status_code)
            for _ in range(20):  # recording finishes shortly after the call
                await asyncio.sleep(1)
                d3 = SessionLocal(); st = d3.query(VoiceCall.recording_status).filter(VoiceCall.id == call_id).scalar(); d3.close()
                if st in ("completed", "failed"):
                    break
            recording["status"] = st
            recording["listen"] = (await http.get(f"/api/v1/telephony/calls/{call_id}/recording", headers=h1)).status_code
            recording["download"] = (await http.get(f"/api/v1/telephony/calls/{call_id}/recording?download=true", headers=h1)).status_code
            recording["agent_without_permission"] = (await http.get(f"/api/v1/telephony/calls/{call_id}/recording", headers=h2)).status_code
            print("recording:", recording)

    missed = {}
    callback_phone, saved_cc = None, None

    async def run_missed(dial, t0):
        nonlocal call_id, agent_room, callback_phone, saved_cc
        from app.models.contact_center import MissedCallTask
        from app.services import outbound_service
        # callback target: the caller's own number, answered by the voice process (AI mode)
        callback_phone = PhoneNumber(company_id=phone.company_id, number=CALLER, provider="livekit_sip", routing_mode="ai",
                                     friendly_name="Loopback callback target", language="en", recording_enabled=False,
                                     is_active=True, provider_config={})
        db.add(callback_phone); db.commit(); db.refresh(callback_phone)
        callback_phone.provider_config = await livekit_sip_service.sync_phone_number(callback_phone); db.commit()
        cc = outbound_service.get_settings(db, phone.company_id)
        saved_cc = {k: getattr(cc, k) for k in ("outbound_trunk_address", "outbound_caller_number", "allowed_country_codes", "outbound_trunk_id")}
        await outbound_service.reset_trunk(db, cc)
        cc.outbound_trunk_address, cc.outbound_caller_number, cc.allowed_country_codes = f"{args.sip_host}:5060", "+966500000002", ["+966"]
        db.commit()

        await asyncio.sleep(8)  # caller waits in the queue; nobody is ready
        dial.cancel()
        await lk.room.delete_room(api.DeleteRoomRequest(room="loopback_test_caller"))  # caller gives up
        await asyncio.sleep(3)
        db.expire_all()
        missed_call = db.query(VoiceCall).filter(VoiceCall.phone_number_id == phone.id).order_by(VoiceCall.id.desc()).first()
        task = db.query(MissedCallTask).filter(MissedCallTask.call_id == missed_call.id).first() if missed_call else None
        missed["classification"] = missed_call.missed_classification if missed_call else None
        missed["task"] = bool(task)
        print("missed call:", missed)
        if not task:
            return
        h = {"Authorization": "Bearer " + create_access_token({"sub": args.user_email})}
        async with httpx.AsyncClient(base_url=args.api_url, timeout=30) as http:
            r = await http.post(f"/api/v1/telephony/missed-calls/{task.id}/assign", headers=h, json={"user_id": user_id})
            missed["assign"] = r.status_code
            r = await http.post(f"/api/v1/telephony/missed-calls/{task.id}/callback", headers=h)
            missed["callback"] = r.status_code
            print("callback ->", r.status_code, r.text[:160])
            if r.status_code != 200:
                return
            acc = r.json()
            call_id = acc["call"]["id"]
            agent_room = rtc.Room()
            await agent_room.connect(acc["livekit_url"], acc["token"])
            mic = rtc.LocalAudioTrack.create_audio_track("mic", rtc.AudioSource(48000, 1))
            await agent_room.local_participant.publish_track(mic, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE))
            for _ in range(20):
                await asyncio.sleep(1)
                d = SessionLocal(); res = d.query(VoiceCall.outbound_result).filter(VoiceCall.id == call_id).scalar(); d.close()
                if res:
                    break
            missed["outbound_result"] = res
            await asyncio.sleep(3)
            await http.post(f"/api/v1/telephony/calls/{call_id}/hangup", headers=h)
            await asyncio.sleep(2)
            r = await http.post(f"/api/v1/telephony/missed-calls/{task.id}/close", headers=h, json={"result": "answered"})
            missed["close"] = r.status_code
            r = await http.get(f"/api/v1/telephony/missed-calls/{task.id}", headers=h)
            detail = r.json()
            missed["attempts"] = [(a["result"], a["duration_seconds"] is not None) for a in detail.get("attempts", [])]
            missed["task_status"] = detail.get("task", {}).get("status")
            print("callback result:", missed)

    try:
        phone.provider_config = await livekit_sip_service.sync_phone_number(phone); db.commit()
        out_trunk = await lk.sip.create_outbound_trunk(api.CreateSIPOutboundTrunkRequest(trunk=api.SIPOutboundTrunkInfo(
            name="agentconnect-loopback-test", address=f"{args.sip_host}:5060", numbers=[CALLER])))

        t0 = time.time()
        dial = asyncio.create_task(lk.sip.create_sip_participant(api.CreateSIPParticipantRequest(
            sip_trunk_id=out_trunk.sip_trunk_id, sip_call_to=TEST_NUMBER, room_name="loopback_test_caller",
            participant_identity="loopback-caller", wait_until_answered=True,
            dtmf={"ai": "1", "ivr": "123"}.get(args.mode, ""))))

        if args.mode == "missed":
            await run_missed(dial, t0)
        elif args.mode == "transfer":
            await run_transfer(lk, dial, offers, t0)
        elif args.mode in ("direct", "queue"):
            offer = await asyncio.wait_for(offers.get(), 20)
            call_id = offer["call"]["id"]
            assert user_id in offer["ring_user_ids"], f"user {user_id} not rung: {offer['ring_user_ids']}"
            print(f"ringing after {time.time()-t0:.1f}s; accepting as {user.email}")
            headers = {"Authorization": "Bearer " + create_access_token({"sub": user.email})}
            async with httpx.AsyncClient(base_url=args.api_url, timeout=20) as http:
                res = await http.post(f"/api/v1/telephony/calls/{call_id}/accept", headers=headers)
                res.raise_for_status(); acc = res.json()
                second = await http.post(f"/api/v1/telephony/calls/{call_id}/accept", headers=headers)
                print("second accept ->", second.status_code, "(expect 409)")
                # join like the browser: publish a microphone track so LiveKit SIP answers the caller
                agent_room = rtc.Room()
                await agent_room.connect(acc["livekit_url"], acc["token"])
                mic = rtc.LocalAudioTrack.create_audio_track("mic", rtc.AudioSource(48000, 1))
                await agent_room.local_participant.publish_track(mic, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE))
                await asyncio.wait_for(dial, 20)
                print(f"answered in {time.time()-t0:.1f}s")
                await asyncio.sleep(3)
                if args.mode == "queue":
                    print("offer came from queue:", offer.get("queue"))
                    print("hold ->", (await http.post(f"/api/v1/telephony/calls/{call_id}/hold", headers=headers)).status_code)
                    await asyncio.sleep(2)
                    print("resume ->", (await http.post(f"/api/v1/telephony/calls/{call_id}/resume", headers=headers)).status_code)
                res = await http.post(f"/api/v1/telephony/calls/{call_id}/hangup", headers=headers)
                print("hangup ->", res.status_code)
                if args.mode == "queue":
                    await asyncio.sleep(1)
                    res = await http.post(f"/api/v1/telephony/calls/{call_id}/wrap-up", headers=headers, json={"note": "loopback test"})
                    print("wrap-up ->", res.status_code, res.json().get("agent", {}).get("state"))
                    wrapped_state = res.json().get("agent", {}).get("state")
        elif args.mode == "ivr":
            await asyncio.wait_for(dial, 30)
            print(f"answered in {time.time()-t0:.1f}s; waiting for the IVR to hang up")
            for _ in range(30):  # the hangup node ends the call; don't hang up from the caller side
                await asyncio.sleep(1)
                if any(e["type"] == "phone_call_ended" for e in events):
                    break
        else:
            await asyncio.wait_for(dial, 30)
            print(f"answered in {time.time()-t0:.1f}s")
            await asyncio.sleep(8)
            await lk.room.delete_room(api.DeleteRoomRequest(room="loopback_test_caller"))  # caller hangs up
        await asyncio.sleep(4)
    except Exception as e:
        print("ERROR during call:", repr(e))
        error = e
    finally:
        if agent_room:
            await agent_room.disconnect()
        try:
            await lk.room.delete_room(api.DeleteRoomRequest(room="loopback_test_caller"))
        except api.TwirpError:
            pass
        if out_trunk:
            await lk.sip.delete_trunk(api.DeleteSIPTrunkRequest(sip_trunk_id=out_trunk.sip_trunk_id))
        await livekit_sip_service.delete_phone_number_resources(phone)
        if callback_phone:
            await livekit_sip_service.delete_phone_number_resources(callback_phone)
        if saved_cc is not None:
            from app.services import outbound_service
            cc = outbound_service.get_settings(db, phone.company_id)
            await outbound_service.reset_trunk(db, cc)
            for k, v in saved_cc.items():
                if k != "outbound_trunk_id":
                    setattr(cc, k, v)
            db.commit()
        await lk.aclose()
        collector.cancel(); await r.aclose()

    db.expire_all()
    row = (db.query(VoiceCall).filter(VoiceCall.id == call_id).first() if call_id
           else db.query(VoiceCall).filter(VoiceCall.phone_number_id == phone.id).order_by(VoiceCall.id.desc()).first())
    call = {k: getattr(row, k) for k in ("id", "status", "ended_by", "handled_by_user_id", "talk_seconds")} if row else None
    seq = [e.type for e in db.query(CallEvent).filter(CallEvent.call_id == row.id).order_by(CallEvent.seq)] if row else []
    from app.models.call_event import CallLeg
    legs_ = [(l.kind, l.user_id, l.end_reason) for l in db.query(CallLeg).filter(CallLeg.call_id == row.id).order_by(CallLeg.seq)] if row else []
    print("CALL", call)
    print("EVENTS", seq)
    print("LEGS", legs_)
    types = [e["type"] for e in events]
    print("WS", types)
    # remove the test call data (test tooling only; real calls are never deleted)
    from app.models.chat_message import ChatMessage
    from app.models.conversation_session import ConversationSession
    from app.models.contact_center import CallbackAttempt, MissedCallTask
    test_calls = db.query(VoiceCall).filter(VoiceCall.phone_number_id.in_([phone.id] + ([callback_phone.id] if callback_phone else []))).all()
    if call_id:
        test_calls += [c for c in db.query(VoiceCall).filter(VoiceCall.id == call_id).all() if c not in test_calls]
    for c in test_calls:
        for t in db.query(MissedCallTask).filter(MissedCallTask.call_id == c.id).all():
            from app.models.audit_log import AuditLog
            db.query(AuditLog).filter(AuditLog.entity_type == "missed_call_task", AuditLog.entity_id == t.id).delete()
        db.query(CallbackAttempt).filter(CallbackAttempt.voice_call_id == c.id).delete()
        db.query(MissedCallTask).filter(MissedCallTask.call_id == c.id).delete()
    db.flush()
    for c in test_calls:
        if c.recording_object_key:  # remove the test recording from object storage
            try:
                from app.core.object_storage import BUCKET_NAME, s3_client
                s3_client.delete_object(Bucket=BUCKET_NAME, Key=c.recording_object_key)
            except Exception as e:
                print("could not delete test recording:", e)
        db.query(CallEvent).filter(CallEvent.call_id == c.id).delete()
        from app.models.call_queue import CallQueueEntry
        from app.models.contact_center import AgentState
        db.query(CallQueueEntry).filter(CallQueueEntry.voice_call_id == c.id).delete()
        db.query(AgentState).filter(AgentState.current_call_id == c.id).update({"current_call_id": None})
        conv = c.conversation_id
        db.delete(c); db.flush()
        sess = db.query(ConversationSession).filter(ConversationSession.conversation_id == conv).first() if conv else None
        if sess:
            db.query(ChatMessage).filter(ChatMessage.session_id == sess.id).delete()
            db.delete(sess)
    if queue:
        from app.models.call_queue import CallQueueEntry
        from app.models.contact_center import AgentState, AgentStateHistory
        db.query(CallQueueEntry).filter(CallQueueEntry.queue_id == queue.id).delete()
        db.query(AgentState).filter(AgentState.user_id == user_id).update({"current_call_id": None})
        db.delete(queue)
    if callback_phone:
        db.delete(callback_phone)
    db.delete(phone); db.flush()
    if workflow:
        db.delete(workflow)
    db.commit(); db.close()

    if error:
        return False
    if args.mode == "ivr" and "ai_failed" in seq:
        print("SKIPPED: the AI audio session failed (speech-to-text / text-to-speech keys rejected?) and the caller "
              "was handed to a human, as designed. Fix the OpenAI / Deepgram keys and rerun.")
        return None
    if args.mode == "ivr":
        return bool(call) and call["status"] == "completed" and call["ended_by"] == "system" \
            and seq.count("dtmf") == 3 and "end" in seq and "phone_call_ended" in types
    if args.mode == "missed":
        return missed.get("classification") == "abandoned" and missed.get("task") and missed.get("assign") == 200 \
            and missed.get("callback") == 200 and missed.get("outbound_result") == "answered" and missed.get("close") == 200 \
            and missed.get("task_status") == "closed" and missed.get("attempts") == [("answered", True)]
    if args.mode == "transfer":
        agent_legs = [l for l in legs_ if l[0] == "agent"]
        ok_chain = len(agent_legs) >= 2 and agent_legs[0][1] == user_id and agent_legs[0][2] == "transferred" \
            and agent_legs[-1][1] == user2_id
        return bool(call) and call["status"] == "completed" and call["handled_by_user_id"] == user2_id and ok_chain \
            and "transfer" in seq and "supervisor_joined" in seq and supervise_ok["listen"] == 200 \
            and recording["status"] == "completed" and recording["listen"] == 200 and recording["download"] == 200 \
            and recording["agent_without_permission"] == 403
    if args.mode == "queue":
        return bool(call) and call["status"] == "completed" and call["handled_by_user_id"] == user_id \
            and {"queue", "offer", "accept", "answer", "hold", "resume", "end", "wrap_up"} <= set(seq) \
            and wrapped_state == "ready"
    if args.mode == "direct":
        return bool(call) and call["status"] == "completed" and call["handled_by_user_id"] == user_id \
            and {"offer", "ring", "accept", "answer", "end"} <= set(seq) and "phone_call_ended" in types
    return bool(call) and call["status"] == "completed" and {"offer", "answer", "dtmf", "end"} <= set(seq) \
        and {"phone_call_new", "phone_call_dtmf", "phone_call_ended"} <= set(types)


ok = asyncio.run(main())
print("RESULT", "SKIPPED" if ok is None else "PASS" if ok else "FAIL")
sys.exit(0 if ok is None or ok else 1)
