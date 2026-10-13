"""
Concurrency test (NFR-005): N simultaneous calls through LiveKit SIP to a temporary AI-answered number.
Reports answer-time percentiles and failures, then removes everything it created.

Answer time depends on warm voice processes: each call needs one; calls beyond
TELEPHONY_VOICE_IDLE_PROCESSES wait for a new process to start (~15-20 s). Size the idle pool for
your expected concurrent calls.

Run from backend/ (voice process running):
  python -m scripts.telephony_load_test --sip-host 192.168.31.107 --calls 10 --hold 10
"""
import argparse
import asyncio
import statistics
import sys
import time

from livekit import api

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.call_event import CallEvent, CallLeg
from app.models.chat_message import ChatMessage
from app.models.conversation_session import ConversationSession
from app.models.phone_number import PhoneNumber
from app.models.voice_call import VoiceCall
from app.services import livekit_sip_service

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("--sip-host", required=True)
parser.add_argument("--calls", type=int, default=5)
parser.add_argument("--hold", type=int, default=10, help="seconds each call stays connected")
parser.add_argument("--company-id", type=int, default=1)
args = parser.parse_args()
NUMBER = "000997"


async def main() -> bool:
    db = SessionLocal()
    phone = PhoneNumber(company_id=args.company_id, number=NUMBER, provider="livekit_sip", routing_mode="ai",
                        friendly_name="Load test", language="en", recording_enabled=False, is_active=True, provider_config={})
    db.add(phone); db.commit(); db.refresh(phone)
    lk = api.LiveKitAPI(settings.LIVEKIT_URL.replace("ws://", "http://"), settings.LIVEKIT_API_KEY, settings.LIVEKIT_API_SECRET)
    trunk = None
    results = []
    try:
        phone.provider_config = await livekit_sip_service.sync_phone_number(phone); db.commit()
        trunk = await lk.sip.create_outbound_trunk(api.CreateSIPOutboundTrunkRequest(trunk=api.SIPOutboundTrunkInfo(
            name="agentconnect-load-test", address=f"{args.sip_host}:5060", numbers=["+966500009999"])))

        async def one(i: int):
            t0 = time.monotonic()
            room = f"load_test_caller_{i}"
            try:
                await lk.sip.create_sip_participant(api.CreateSIPParticipantRequest(
                    sip_trunk_id=trunk.sip_trunk_id, sip_call_to=NUMBER, room_name=room,
                    participant_identity=f"load-{i}", wait_until_answered=True))
                answered = time.monotonic() - t0
                await asyncio.sleep(args.hold)
                results.append(("ok", answered))
            except Exception as e:
                results.append(("failed", str(e)[:120]))
            finally:
                try:
                    await lk.room.delete_room(api.DeleteRoomRequest(room=room))
                except api.TwirpError:
                    pass

        t_start = time.monotonic()
        await asyncio.gather(*(one(i) for i in range(args.calls)))
        elapsed = time.monotonic() - t_start
        await asyncio.sleep(4)
    finally:
        if trunk:
            await lk.sip.delete_trunk(api.DeleteSIPTrunkRequest(sip_trunk_id=trunk.sip_trunk_id))
        await livekit_sip_service.delete_phone_number_resources(phone)
        await lk.aclose()
        db.expire_all()
        calls = db.query(VoiceCall).filter(VoiceCall.phone_number_id == phone.id).all()
        completed = sum(1 for c in calls if c.status == "completed")
        for c in calls:
            db.query(CallEvent).filter(CallEvent.call_id == c.id).delete()
            db.query(CallLeg).filter(CallLeg.call_id == c.id).delete()
            conv = c.conversation_id
            db.delete(c); db.flush()
            s = db.query(ConversationSession).filter(ConversationSession.conversation_id == conv).first()
            if s:
                db.query(ChatMessage).filter(ChatMessage.session_id == s.id).delete()
                db.delete(s)
        db.delete(phone); db.commit(); db.close()

    ok = sorted(r[1] for r in results if r[0] == "ok")
    failed = [r[1] for r in results if r[0] == "failed"]
    print(f"calls: {args.calls}  answered: {len(ok)}  failed: {len(failed)}  call records completed: {completed}  wall time: {elapsed:.1f}s")
    if ok:
        p95 = ok[min(len(ok) - 1, int(round(0.95 * (len(ok) - 1))))]
        print(f"answer time  min {ok[0]:.1f}s  median {statistics.median(ok):.1f}s  p95 {p95:.1f}s  max {ok[-1]:.1f}s")
    for f in failed[:5]:
        print("  failure:", f)
    passed = not failed and completed == args.calls
    print("RESULT", "PASS" if passed else "FAIL")
    return passed


sys.exit(0 if asyncio.run(main()) else 1)
