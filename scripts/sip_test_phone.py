"""Scripted SIP softphone for tests (UDP): REGISTER / INVITE with digest auth, answer an INVITE with 486."""
import hashlib
import re
import socket
import time
import uuid


class Phone:
    def __init__(self, user, password, server, realm):
        self.user, self.password, self.server, self.realm = user, password, server, realm
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("0.0.0.0", 0))
        self.port = self.sock.getsockname()[1]
        self.ip = server[0]
        self.tag = uuid.uuid4().hex[:8]
        self.cseq = 1

    def _send(self, method, uri, to, call_id, auth="", body="", extra=""):
        lines = [f"{method} {uri} SIP/2.0",
                 f"Via: SIP/2.0/UDP {self.ip}:{self.port};branch=z9hG4bK{uuid.uuid4().hex[:12]};rport",
                 "Max-Forwards: 70", f"From: <sip:{self.user}@{self.server[0]}>;tag={self.tag}", f"To: <{to}>",
                 f"Call-ID: {call_id}", f"CSeq: {self.cseq} {method}", f"Contact: <sip:{self.user}@{self.ip}:{self.port}>",
                 "User-Agent: agentconnect-ha-test"]
        if auth:
            lines.append(auth)
        if extra:
            lines.append(extra)
        if body:
            lines.append("Content-Type: application/sdp")
        lines.append(f"Content-Length: {len(body)}")
        self.sock.sendto(("\r\n".join(lines) + "\r\n\r\n" + body).encode(), self.server)
        self.cseq += 1

    def recv(self, wait=6.0, want=None):
        end = time.time() + wait
        while time.time() < end:
            self.sock.settimeout(max(0.1, end - time.time()))
            try:
                data, src = self.sock.recvfrom(65535)
            except socket.timeout:
                break
            msg = data.decode(errors="ignore")
            if want is None or want(msg):
                return msg, src
        return None, None

    def _digest(self, challenge, method, uri, header):
        nonce = re.search(r'nonce="([^"]+)"', challenge).group(1)
        ha1 = hashlib.md5(f"{self.user}:{self.realm}:{self.password}".encode()).hexdigest()
        ha2 = hashlib.md5(f"{method}:{uri}".encode()).hexdigest()
        resp = hashlib.md5(f"{ha1}:{nonce}:{ha2}".encode()).hexdigest()
        return f'{header}: Digest username="{self.user}", realm="{self.realm}", nonce="{nonce}", uri="{uri}", response="{resp}", algorithm=MD5'

    def register(self, expires=300):
        uri, to, cid = f"sip:{self.server[0]}:{self.server[1]}", f"sip:{self.user}@{self.server[0]}", uuid.uuid4().hex
        self._send("REGISTER", uri, to, cid, extra=f"Expires: {expires}")
        r, _ = self.recv(want=lambda m: m.startswith("SIP/2.0 401"))
        if not r:
            return None
        self._send("REGISTER", uri, to, cid, auth=self._digest(r, "REGISTER", uri, "Authorization"), extra=f"Expires: {expires}")
        r, _ = self.recv(want=lambda m: m.startswith("SIP/2.0") and int(m.split()[1]) >= 200)
        return int(r.split()[1]) if r else None

    def call(self, user):
        """Send an authenticated INVITE; returns the call id (responses are read with final_response)."""
        uri, cid = f"sip:{user}@{self.server[0]}:{self.server[1]}", uuid.uuid4().hex
        sdp = (f"v=0\r\no=- 1 1 IN IP4 {self.ip}\r\ns=t\r\nc=IN IP4 {self.ip}\r\nt=0 0\r\n"
               f"m=audio 40000 RTP/AVP 0\r\na=rtpmap:0 PCMU/8000\r\n")
        self._send("INVITE", uri, f"sip:{user}@{self.server[0]}", cid, body=sdp)
        r, _ = self.recv(want=lambda m: m.startswith("SIP/2.0 40"))
        if r:
            hdr = "Proxy-Authorization" if r.startswith("SIP/2.0 407") else "Authorization"
            self._ack(uri, user, cid, r)
            self._send("INVITE", uri, f"sip:{user}@{self.server[0]}", cid, auth=self._digest(r, "INVITE", uri, hdr), body=sdp)
        return cid

    def _ack(self, uri, user, cid, response):
        to = re.search(r"^To: (.+)$", response, re.M | re.I).group(1).strip()
        via = re.search(r"^Via: (.+)$", response, re.M | re.I).group(1).strip()
        cseq = re.search(r"^CSeq: (\d+)", response, re.M | re.I).group(1)
        msg = "\r\n".join([f"ACK {uri} SIP/2.0", f"Via: {via}", "Max-Forwards: 70", f"From: <sip:{self.user}@{self.server[0]}>;tag={self.tag}",
                           f"To: {to}", f"Call-ID: {cid}", f"CSeq: {cseq} ACK", "Content-Length: 0"]) + "\r\n\r\n"
        self.sock.sendto(msg.encode(), self.server)

    def final_response(self, cid, wait=20.0):
        r, _ = self.recv(wait, want=lambda m: m.startswith("SIP/2.0") and f"Call-ID: {cid}" in m and int(m.split()[1]) >= 200)
        return int(r.split()[1]) if r else None

    def answer_busy(self, wait=20.0):
        """Wait for an INVITE; reply 486. Returns the address it came from."""
        msg, src = self.recv(wait, want=lambda m: m.startswith("INVITE "))
        if not msg:
            return None
        keep = [l for l in msg.split("\r\n") if re.match(r"^(Via|From|To|Call-ID|CSeq|Record-Route):", l, re.I)]
        keep = [l + (f";tag={uuid.uuid4().hex[:6]}" if l.lower().startswith("to:") and "tag=" not in l else "") for l in keep]
        self.sock.sendto(("SIP/2.0 486 Busy Here\r\n" + "\r\n".join(keep) + "\r\nContent-Length: 0\r\n\r\n").encode(), src)
        return src
