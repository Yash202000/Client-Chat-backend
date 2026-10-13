"""
SIP registrar high-availability test: two registrars sharing registrations in the database.

  phone 1 registers with registrar B, phone 2 with registrar A
  1. registrations are in the database (kamailio.location) with the registrar they came in on
  2. phone 2 calls phone 1 through A -> A forwards to B -> B delivers it (phone 1 answers 486)
  3. B restarts -> phone 1 is still reachable without registering again (registrations survived)
  4. B is down -> A reaches phone 1 directly
Uses two temporary users with SIP accounts; restores registrar B and removes everything after.

Run from backend/ with both registrars up (docker compose --profile ha up -d sip-registrar sip-registrar-2):
  python -m scripts.sip_registrar_ha_test [--a 192.168.31.107:5080] [--b 192.168.31.107:5082] [--b-container backend-sip-registrar-2-1]
"""
import argparse
import hashlib
import subprocess
import sys
import time
import uuid

from sqlalchemy import text

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.contact_center import SipAccount
from app.models.user import User
from scripts.sip_test_phone import Phone

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("--a", default=settings.TELEPHONY_SIP_REGISTRAR_ADDRESS)
parser.add_argument("--b", default="192.168.31.107:5082")
parser.add_argument("--b-container", default="backend-sip-registrar-2-1")
parser.add_argument("--company-id", type=int, default=1)
args = parser.parse_args()
REALM = settings.TELEPHONY_SIP_REALM
A = (args.a.rsplit(":", 1)[0], int(args.a.rsplit(":", 1)[1]))
B = (args.b.rsplit(":", 1)[0], int(args.b.rsplit(":", 1)[1]))
failures = []


def check(name, cond, detail=""):
    print(f"  {'ok  ' if cond else 'FAIL'} {name}{(' -> ' + str(detail)) if detail and not cond else ''}")
    if not cond:
        failures.append(name)


def docker(*a):
    return subprocess.run(["docker", *a], capture_output=True, text=True)


def wait_healthy(container, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        if docker("inspect", "-f", "{{.State.Health.Status}}", container).stdout.strip() == "healthy":
            return True
        time.sleep(2)
    return False


def main() -> bool:
    db = SessionLocal()
    tag = uuid.uuid4().hex[:6]
    users, names = [], []
    for i in (1, 2):
        u = User(email=f"ha_{tag}_{i}@test.local", hashed_password="x", is_active=True, company_id=args.company_id)
        db.add(u); db.flush()
        name = f"ha{tag}{i}"
        db.add(SipAccount(company_id=args.company_id, user_id=u.id, username=name, realm=REALM, enabled=True,
                          ha1=hashlib.md5(f"{name}:{REALM}:pw-{tag}".encode()).hexdigest()))
        users.append(u); names.append(name)
    db.commit()
    p1, p2 = Phone(names[0], f"pw-{tag}", B, REALM), Phone(names[1], f"pw-{tag}", A, REALM)
    try:
        print("1. Registrations in the database")
        check("phone 1 registers with registrar B", p1.register() == 200)
        check("phone 2 registers with registrar A", p2.register() == 200)
        rows = dict(db.execute(text("SELECT username, socket FROM kamailio.location WHERE username IN (:a, :b)"),
                               {"a": names[0], "b": names[1]}).fetchall())
        check("phone 1's registration names registrar B", rows.get(names[0], "").endswith(f"{B[0]}:{B[1]}"), rows)
        check("phone 2's registration names registrar A", rows.get(names[1], "").endswith(f"{A[0]}:{A[1]}"), rows)

        print("2. Call across registrars (A -> B -> phone)")
        cid = p2.call(names[0])
        src = p1.answer_busy()
        check("phone 1 gets the call from registrar B", src == B, src)
        check("phone 2 hears phone 1's answer (486)", p2.final_response(cid) == 486)

        print("3. Registrar B restarts: registrations survive")
        docker("restart", args.b_container)
        check("registrar B healthy again", wait_healthy(args.b_container))
        time.sleep(3)
        cid = p2.call(names[0])
        src = p1.answer_busy()
        check("phone 1 reachable without registering again", src == B, src)
        check("call completes", p2.final_response(cid) == 486)

        print("4. Registrar B down: A reaches the phone directly")
        docker("stop", args.b_container)
        t = time.time()
        cid = p2.call(names[0])
        src = p1.answer_busy(wait=25)
        check("phone 1 gets the call from registrar A", src == A, src)
        check(f"after the forwarding timeout ({time.time() - t:.0f}s)", src is not None)
        check("call completes", p2.final_response(cid) == 486)
        docker("start", args.b_container)
        check("registrar B back", wait_healthy(args.b_container))

    finally:
        if docker("inspect", "-f", "{{.State.Running}}", args.b_container).stdout.strip() != "true":
            docker("start", args.b_container)
        for p in (p1, p2):
            try:
                p.register(expires=0)
            except Exception:
                pass
        db.execute(text("DELETE FROM kamailio.location WHERE username IN (:a, :b)"), {"a": names[0], "b": names[1]})
        for u in users:
            db.query(SipAccount).filter(SipAccount.user_id == u.id).delete()
            db.delete(u)
        db.commit(); db.close()
    print("RESULT", "PASS" if not failures else f"FAIL ({', '.join(failures)})")
    return not failures


sys.exit(0 if main() else 1)
