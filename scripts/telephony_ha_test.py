"""
High-availability test for the contact-centre media stack (the HA lab: telephony/ha/docker-compose.yml).

A scripted softphone registers with a registrar and calls a contact-centre number; after each failure
the call must still reach LiveKit and be recorded by the backend:
  1. both LiveKit nodes form one cluster (a room made on one is seen on the other)
  2. baseline call through registrar -> LiveKit SIP
  3. a LiveKit SIP node is down       -> the registrar sends calls to the other node
  4. a LiveKit node is down           -> backend API + agents' address switch to the other node; the SIP node
                                         of that side reaches LiveKit through its local LB; calls work
  5. the Redis master is down         -> Sentinel promotes the replica; LiveKit, backend fan-out, calls work
Everything is started again afterwards; test data is removed.

Needs: the HA lab up, the backend test API on :8010 with the lab settings (LIVEKIT_URLS, REDIS_SENTINELS),
and this script run with the same settings. From backend/:
  python -m scripts.telephony_ha_test [--registrar 192.168.31.107:5180] [--company-id 1]
"""
import argparse
import asyncio
import hashlib
import subprocess
import sys
import time
import uuid

from livekit import api
from sqlalchemy import text

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.contact_center import SipAccount
from app.models.phone_number import PhoneNumber
from app.models.user import User
from app.models.voice_call import VoiceCall
from app.services import livekit_nodes, livekit_sip_service
from scripts.sip_test_phone import Phone

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("--registrar", default="192.168.31.107:5180")
parser.add_argument("--company-id", type=int, default=1)
parser.add_argument("--project", default="agentconnect-ha")
args = parser.parse_args()
REGISTRAR = (args.registrar.rsplit(":", 1)[0], int(args.registrar.rsplit(":", 1)[1]))
NODES = {"a": "http://localhost:7960", "b": "http://localhost:7970"}
failures = []


def check(name, cond, detail=""):
    print(f"  {'ok  ' if cond else 'FAIL'} {name}{(' -> ' + str(detail)) if detail and not cond else ''}")
    if not cond:
        failures.append(name)


def svc(action, service):
    subprocess.run(["docker", action, f"{args.project}-{service}-1"], capture_output=True, text=True)


def sentinel_master() -> str:
    r = subprocess.run(["docker", "exec", f"{args.project}-sentinel-1-1", "redis-cli", "-p", "26390",
                        "sentinel", "get-master-addr-by-name", "agentconnect"], capture_output=True, text=True)
    return ":".join(r.stdout.split())


def node_api(node: str) -> api.LiveKitAPI:
    return api.LiveKitAPI(NODES[node], settings.LIVEKIT_API_KEY, settings.LIVEKIT_API_SECRET)


def handled_by(call_id: str) -> str:
    for node in ("a", "b"):
        r = subprocess.run(["docker", "logs", "--since", "2m", f"{args.project}-sip-{node}-1"], capture_output=True, text=True)
        if call_id in r.stdout + r.stderr:
            return node
    return "?"


class Caller:
    def __init__(self, db, phone: Phone, number: PhoneNumber, sip_user: str):
        self.db, self.phone, self.number, self.sip_user = db, phone, number, sip_user

    async def call(self, label: str) -> tuple[bool, str]:
        """Dial the number; True when the backend records the call (via the LiveKit webhook)."""
        before = {c.id for c in self.db.query(VoiceCall.id).filter(VoiceCall.phone_number_id == self.number.id)}
        t = time.time()
        cid = self.phone.call(self.number.number)
        call = None
        while time.time() - t < 25 and call is None:
            await asyncio.sleep(1)
            self.db.expire_all()
            call = (self.db.query(VoiceCall).filter(VoiceCall.phone_number_id == self.number.id, ~VoiceCall.id.in_(before or [0]))
                    .order_by(VoiceCall.id.desc()).first())
        node = handled_by(cid)
        ok = call is not None and call.from_number == self.sip_user
        check(f"{label}: call reaches LiveKit and is recorded ({time.time() - t:.0f}s, LiveKit SIP node {node})", ok,
              call.from_number if call else "no call record")
        if call is not None:
            lk = livekit_sip_service._api()
            try:
                await lk.room.delete_room(api.DeleteRoomRequest(room=call.room_name))
            except Exception:
                pass
            finally:
                await lk.aclose()
        await asyncio.sleep(2)
        return ok, node


async def wait_for(cond, timeout=40):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        await asyncio.sleep(1)
    return False


async def main() -> bool:
    db = SessionLocal()
    tag = uuid.uuid4().hex[:6]
    realm = settings.TELEPHONY_SIP_REALM
    user = User(email=f"ha_{tag}@test.local", hashed_password="x", is_active=True, company_id=args.company_id)
    db.add(user); db.flush()
    sip_user = f"hacall{tag}"
    db.add(SipAccount(company_id=args.company_id, user_id=user.id, username=sip_user, realm=realm, enabled=True,
                      ha1=hashlib.md5(f"{sip_user}:{realm}:pw-{tag}".encode()).hexdigest()))
    number = PhoneNumber(company_id=args.company_id, number="000998", provider="livekit_sip", routing_mode="direct",
                         friendly_name="HA test", language="en", recording_enabled=False, is_active=True, provider_config={})
    db.add(number); db.commit(); db.refresh(number)
    phone = Phone(sip_user, f"pw-{tag}", REGISTRAR, realm)
    stopped = []
    try:
        number.provider_config = await livekit_sip_service.sync_phone_number(number); db.commit()
        caller = Caller(db, phone, number, sip_user)
        check("softphone registers with the registrar", phone.register() == 200)

        print("1. LiveKit cluster")
        start_master = sentinel_master()
        check("Sentinel knows the Redis master", start_master.endswith((":6390", ":6391")), start_master)
        room = f"ha_{tag}"
        a, b = node_api("a"), node_api("b")
        try:
            await a.room.create_room(api.CreateRoomRequest(name=room, empty_timeout=60))
            seen = [r.name for r in (await b.room.list_rooms(api.ListRoomsRequest(names=[room]))).rooms]
            check("room made on node a is listed by node b", seen == [room], seen)
            await b.room.delete_room(api.DeleteRoomRequest(room=room))
        finally:
            await a.aclose(); await b.aclose()
        check("backend sees both nodes healthy", all(n["healthy"] for n in livekit_nodes.status()), livekit_nodes.status())

        print("2. Baseline")
        await caller.call("baseline")

        print("3. LiveKit SIP node a down")
        svc("stop", "sip-a"); stopped.append("sip-a")
        for i in (1, 2):
            ok, node = await caller.call(f"call {i}")
            check(f"call {i} handled by LiveKit SIP node b", node == "b", node)
        svc("start", "sip-a"); stopped.remove("sip-a")
        await asyncio.sleep(12)  # registrar probes see node a again

        print("4. LiveKit node a down")
        svc("stop", "livekit-a"); stopped.append("livekit-a")
        await asyncio.sleep(6)  # health cache
        check("backend API uses node b", livekit_nodes.api_url() == NODES["b"], livekit_nodes.api_url())
        check("agents are sent to node b", livekit_nodes.public_url().endswith(":7970"), livekit_nodes.public_url())
        lk = livekit_sip_service._api()
        try:
            await lk.room.create_room(api.CreateRoomRequest(name=f"{room}_b", empty_timeout=30))
            await lk.room.delete_room(api.DeleteRoomRequest(room=f"{room}_b"))
            check("backend can still create rooms", True)
        except Exception as e:
            check("backend can still create rooms", False, e)
        finally:
            await lk.aclose()
        handled = [(await caller.call(f"node a down, call {i}"))[1] for i in (1, 2)]  # round robin: both SIP nodes
        check("SIP node a (whose own LiveKit is down) also connects calls, via its local LB", "a" in handled, handled)
        svc("start", "livekit-a"); stopped.remove("livekit-a")
        check("node a back and healthy", await wait_for(lambda: livekit_nodes.healthy("ws://localhost:7960")))
        await asyncio.sleep(10)

        print("5. Redis master down (Sentinel failover)")
        old, new, old_port = ("redis-a", "redis-b", 6390) if sentinel_master().endswith(":6390") else ("redis-b", "redis-a", 6391)
        svc("stop", old); stopped.append(old)
        t = time.time()
        promoted = await wait_for(lambda: sentinel_master().endswith(":6391" if new == "redis-b" else ":6390"), timeout=40)
        check(f"Sentinel promotes {new} ({time.time() - t:.0f}s)", promoted, sentinel_master())
        await asyncio.sleep(5)
        from app.core.redis_client import async_redis
        r = async_redis(decode_responses=True)
        try:
            await r.publish(settings.WS_FANOUT_CHANNEL, '{"op":"noop"}')
            info = await r.info("replication")
            check("backend Redis client follows the new master", info.get("role") == "master", info.get("role"))
        except Exception as e:
            check("backend Redis client follows the new master", False, e)
        finally:
            await r.aclose()
        lk = livekit_sip_service._api()
        try:
            await lk.room.create_room(api.CreateRoomRequest(name=f"{room}_r", empty_timeout=30))
            await lk.room.delete_room(api.DeleteRoomRequest(room=f"{room}_r"))
            check("LiveKit keeps working on the new master", True)
        except Exception as e:
            check("LiveKit keeps working on the new master", False, e)
        finally:
            await lk.aclose()
        await caller.call("after Redis failover")
        svc("start", old); stopped.remove(old)

        def old_role():
            return subprocess.run(["docker", "exec", f"{args.project}-{old}-1", "redis-cli", "-p", str(old_port), "role"],
                                  capture_output=True, text=True).stdout.split()[:1]
        check(f"old master {old} rejoins as a replica", await wait_for(lambda: old_role() == ["slave"], timeout=60), old_role())
    finally:
        for s in stopped:
            svc("start", s)
        try:
            phone.register(expires=0)
        except Exception:
            pass
        await livekit_sip_service.delete_phone_number_resources(number)
        from app.models.call_queue import CallQueueEntry
        from app.models.chat_message import ChatMessage
        from app.models.contact_center import MissedCallTask
        from app.models.conversation_session import ConversationSession
        db.rollback()
        for c in db.query(VoiceCall).filter(VoiceCall.phone_number_id == number.id).all():
            db.query(MissedCallTask).filter(MissedCallTask.call_id == c.id).delete()
            db.query(CallQueueEntry).filter(CallQueueEntry.voice_call_id == c.id).delete()
            conv = c.conversation_id
            db.delete(c); db.flush()
            s = db.query(ConversationSession).filter(ConversationSession.conversation_id == conv).first()
            if s:
                db.query(ChatMessage).filter(ChatMessage.session_id == s.id).delete()
                db.delete(s)
        db.delete(number)
        db.execute(text("DELETE FROM kamailio.location WHERE username = :u"), {"u": sip_user})
        db.query(SipAccount).filter(SipAccount.user_id == user.id).delete()
        db.delete(user)
        db.commit(); db.close()
    print("RESULT", "PASS" if not failures else f"FAIL ({', '.join(failures)})")
    return not failures


sys.exit(0 if asyncio.run(main()) else 1)
