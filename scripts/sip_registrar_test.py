"""
SIP registrar test (Kamailio in front of LiveKit SIP) with a scripted softphone — no real phone needed.

Checks: a user's SIP account can register (digest auth); wrong password / disabled account /
deactivated user are refused; a registered phone dialling a contact-centre number reaches LiveKit
SIP and the call is recorded with the SIP username as the caller. Cleans up after itself.

Run from backend/ (registrar, LiveKit, LiveKit SIP and the backend running):
  python -m scripts.sip_registrar_test [--registrar 192.168.31.107:5080] [--user-email user1@gmail.com]
"""
import argparse
import asyncio
import hashlib
import re
import socket
import sys
import time
import uuid

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.call_event import CallEvent
from app.models.contact_center import SipAccount
from app.models.phone_number import PhoneNumber
from app.models.user import User
from app.models.voice_call import VoiceCall
from app.services import livekit_sip_service

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("--registrar", default=settings.TELEPHONY_SIP_REGISTRAR_ADDRESS)
parser.add_argument("--user-email", default="user1@gmail.com")
args = parser.parse_args()
HOST, PORT = args.registrar.rsplit(":", 1)
PORT = int(PORT)
REALM = settings.TELEPHONY_SIP_REALM
SIP_USER, SIP_PASS, TEST_NUMBER = "test1001", "S3cret-pass", "000996"
failures = []


def check(name, cond, detail=""):
    print(f"  {'ok  ' if cond else 'FAIL'} {name}{(' -> ' + str(detail)) if detail and not cond else ''}")
    if not cond:
        failures.append(name)


class Phone:
    """Minimal UDP SIP user agent: REGISTER and INVITE with digest auth."""

    def __init__(self, user, password):
        self.user, self.password = user, password
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("0.0.0.0", 0))
        self.sock.settimeout(5)
        self.port = self.sock.getsockname()[1]
        self.ip = HOST
        self.call_id, self.tag, self.cseq = uuid.uuid4().hex, uuid.uuid4().hex[:8], 1

    def _send(self, method, uri, to_uri, auth=None, body="", extra=""):
        branch = "z9hG4bK" + uuid.uuid4().hex[:12]
        headers = [
            f"{method} {uri} SIP/2.0",
            f"Via: SIP/2.0/UDP {self.ip}:{self.port};branch={branch};rport",
            "Max-Forwards: 70",
            f"From: <sip:{self.user}@{HOST}>;tag={self.tag}",
            f"To: <{to_uri}>",
            f"Call-ID: {self.call_id}",
            f"CSeq: {self.cseq} {method}",
            f"Contact: <sip:{self.user}@{self.ip}:{self.port}>",
            "User-Agent: agentconnect-test-phone",
        ]
        if auth:
            headers.append(auth)
        if extra:
            headers.append(extra)
        if body:
            headers.append("Content-Type: application/sdp")
        headers.append(f"Content-Length: {len(body)}")
        self.sock.sendto(("\r\n".join(headers) + "\r\n\r\n" + body).encode(), (HOST, PORT))
        self.cseq += 1
        return branch

    def responses(self, until_final=True, wait=8.0):
        out, end = [], time.time() + wait
        while time.time() < end:
            try:
                data, _ = self.sock.recvfrom(65535)
            except socket.timeout:
                break
            text = data.decode(errors="ignore")
            if not text.startswith("SIP/2.0"):
                continue
            code = int(text.split()[1])
            out.append((code, text))
            if until_final and code >= 200:
                break
        return out

    def digest(self, challenge, method, uri, header="Authorization"):
        realm = re.search(r'realm="([^"]+)"', challenge).group(1)
        nonce = re.search(r'nonce="([^"]+)"', challenge).group(1)
        ha1 = hashlib.md5(f"{self.user}:{realm}:{self.password}".encode()).hexdigest()
        ha2 = hashlib.md5(f"{method}:{uri}".encode()).hexdigest()
        resp = hashlib.md5(f"{ha1}:{nonce}:{ha2}".encode()).hexdigest()
        return (f'{header}: Digest username="{self.user}", realm="{realm}", nonce="{nonce}", uri="{uri}", '
                f'response="{resp}", algorithm=MD5'), realm

    def register(self):
        uri = f"sip:{HOST}:{PORT}"
        to = f"sip:{self.user}@{HOST}"
        self._send("REGISTER", uri, to, extra="Expires: 300")
        first = self.responses()
        if not first or first[-1][0] != 401:
            return first[-1][0] if first else None, None
        auth, realm = self.digest(first[-1][1], "REGISTER", uri)
        self._send("REGISTER", uri, to, auth=auth, extra="Expires: 300")
        final = self.responses()
        return (final[-1][0] if final else None), realm

    def invite(self, number):
        uri = f"sip:{number}@{HOST}:{PORT}"
        sdp = (f"v=0\r\no=- 1 1 IN IP4 {self.ip}\r\ns=test\r\nc=IN IP4 {self.ip}\r\nt=0 0\r\n"
               f"m=audio 40000 RTP/AVP 0 101\r\na=rtpmap:0 PCMU/8000\r\na=rtpmap:101 telephone-event/8000\r\na=sendrecv\r\n")
        self.call_id = uuid.uuid4().hex
        branch = self._send("INVITE", uri, f"sip:{number}@{HOST}", body=sdp)
        first = self.responses()
        if not first or first[-1][0] not in (401, 407):
            return [c for c, _ in first]
        self._ack(uri, number, first[-1][1], branch)
        hdr = "Proxy-Authorization" if first[-1][0] == 407 else "Authorization"
        auth, _ = self.digest(first[-1][1], "INVITE", uri, header=hdr)
        self.cseq -= 0
        self._send("INVITE", uri, f"sip:{number}@{HOST}", auth=auth, body=sdp)
        got = self.responses(until_final=False, wait=6)
        return [c for c, _ in got]

    def _ack(self, uri, number, response, branch):
        to = re.search(r"^To: (.+)$", response, re.M | re.I).group(1).strip()
        msg = "\r\n".join([
            f"ACK {uri} SIP/2.0", f"Via: SIP/2.0/UDP {self.ip}:{self.port};branch={branch};rport", "Max-Forwards: 70",
            f"From: <sip:{self.user}@{HOST}>;tag={self.tag}", f"To: {to}", f"Call-ID: {self.call_id}",
            f"CSeq: {self.cseq - 1} ACK", "Content-Length: 0"]) + "\r\n\r\n"
        self.sock.sendto(msg.encode(), (HOST, PORT))


async def main() -> bool:
    db = SessionLocal()
    user = db.query(User).filter(User.email == args.user_email).one()
    ha1 = hashlib.md5(f"{SIP_USER}:{REALM}:{SIP_PASS}".encode()).hexdigest()
    existing = db.query(SipAccount).filter(SipAccount.user_id == user.id).first()
    saved = (existing.username, existing.ha1, existing.realm, existing.enabled) if existing else None
    account = existing or SipAccount(company_id=user.company_id, user_id=user.id)
    account.username, account.ha1, account.realm, account.enabled = SIP_USER, ha1, REALM, True
    db.add(account); db.commit()
    phone_row = PhoneNumber(company_id=user.company_id, number=TEST_NUMBER, provider="livekit_sip", routing_mode="direct",
                            friendly_name="Registrar test", language="en", recording_enabled=False, is_active=True, provider_config={})
    db.add(phone_row); db.commit(); db.refresh(phone_row)
    try:
        phone_row.provider_config = await livekit_sip_service.sync_phone_number(phone_row); db.commit()

        print("1. Registration")
        code, realm = Phone(SIP_USER, SIP_PASS).register()
        check("registers with the user's SIP account", code == 200, code)
        check(f"realm is '{REALM}'", realm == REALM, realm)
        code, _ = Phone(SIP_USER, "wrong-password").register()
        check("wrong password refused", code in (401, 403), code)
        code, _ = Phone("nobody-here", "whatever123").register()
        check("unknown user refused", code in (401, 403), code)
        account.enabled = False; db.commit()
        code, _ = Phone(SIP_USER, SIP_PASS).register()
        check("disabled SIP account refused", code in (401, 403), code)
        account.enabled = True; db.commit()
        user.is_active = False; db.commit()
        code, _ = Phone(SIP_USER, SIP_PASS).register()
        check("deactivated user refused", code in (401, 403), code)
        user.is_active = True; db.commit()

        print("2. Call from a registered softphone to a contact-centre number")
        phone = Phone(SIP_USER, SIP_PASS)
        phone.register()
        codes = phone.invite(TEST_NUMBER)
        print("   responses:", codes)
        check("call reaches LiveKit SIP (trying / ringing)", any(c in (100, 180, 183) for c in codes), codes)
        await asyncio.sleep(3)
        db.expire_all()
        call = db.query(VoiceCall).filter(VoiceCall.phone_number_id == phone_row.id).order_by(VoiceCall.id.desc()).first()
        check("call recorded with the SIP username as caller", call is not None and call.from_number == SIP_USER,
              call.from_number if call else None)
    finally:
        # hang up the test call by removing its room, then clean up
        from livekit import api
        lk = livekit_sip_service._api()
        try:
            db.expire_all()
            for c in db.query(VoiceCall).filter(VoiceCall.phone_number_id == phone_row.id).all():
                try:
                    await lk.room.delete_room(api.DeleteRoomRequest(room=c.room_name))
                except Exception:
                    pass
        finally:
            await lk.aclose()
        await asyncio.sleep(2)
        await livekit_sip_service.delete_phone_number_resources(phone_row)
        db.expire_all()
        from app.models.call_queue import CallQueueEntry
        from app.models.chat_message import ChatMessage
        from app.models.contact_center import MissedCallTask
        from app.models.conversation_session import ConversationSession
        for c in db.query(VoiceCall).filter(VoiceCall.phone_number_id == phone_row.id).all():
            db.query(MissedCallTask).filter(MissedCallTask.call_id == c.id).delete()
            db.query(CallQueueEntry).filter(CallQueueEntry.voice_call_id == c.id).delete()
            conv = c.conversation_id
            db.delete(c); db.flush()
            s = db.query(ConversationSession).filter(ConversationSession.conversation_id == conv).first()
            if s:
                db.query(ChatMessage).filter(ChatMessage.session_id == s.id).delete()
                db.delete(s)
        db.delete(phone_row)
        user.is_active = True
        if saved:
            account.username, account.ha1, account.realm, account.enabled = saved
        else:
            db.delete(account)
        db.commit(); db.close()
    print("RESULT", "PASS" if not failures else f"FAIL ({', '.join(failures)})")
    return not failures


sys.exit(0 if asyncio.run(main()) else 1)
