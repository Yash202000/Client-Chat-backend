"""
M7 permission test: admin / compliance endpoints refuse users without the permission and still work
for company Admins. Uses a temporary role with no permissions and a temporary user; removes them after.

Run from backend/:  python -m scripts.permissions_test [--company-id 1]
"""
import argparse
import sys
import uuid

from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.core.security import create_access_token
from app.models.audit_log import AuditLog
from app.models.role import Role
from app.models.user import User

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--company-id", type=int, default=1)
args = parser.parse_args()
failures = []

# (method, path, permission) — admin result: any status except 401/403
ENDPOINTS = [
    ("GET", "/api/v1/audit-logs/", "audit:read"),
    ("GET", "/api/v1/audit-logs/export", "audit:read"),
    ("GET", "/api/v1/security-logs/", "security_log:read"),
    ("GET", "/api/v1/security-logs/stats", "security_log:read"),
    ("GET", "/api/v1/security-logs/critical", "security_log:read"),
    ("DELETE", "/api/v1/security-logs/0", "security_log:delete"),
    ("DELETE", "/api/v1/security-logs/?older_than_days=365", "security_log:delete"),
    ("POST", "/api/v1/export/data", "data:export"),
    ("POST", "/api/v1/routing-rules/", "settings:write"),       # admin: 422 (no body) = passed the check
    ("POST", "/api/v1/custom-fields/", "settings:write"),
    ("POST", "/api/v1/tickets/workflows", "ticket:manage"),
]


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
    role = Role(name=f"__perm_{tag}", description="permission test", company_id=cid)
    db.add(role); db.flush()
    nobody = User(email=f"perm_{tag}@test.local", hashed_password="x", is_active=True, company_id=cid, role_id=role.id)
    db.add(nobody); db.commit()
    H = lambda u: {"Authorization": "Bearer " + create_access_token({"sub": u.email})}  # noqa: E731
    try:
        with TestClient(app) as client:
            print("1. A user without the permissions is refused")
            for method, path, perm in ENDPOINTS:
                r = client.request(method, path, headers=H(nobody))
                check(f"{method} {path.split('?')[0]} -> 403 ({perm})", r.status_code == 403, r.status_code)
            print("2. A company Admin is allowed")
            for method, path, perm in ENDPOINTS:
                r = client.request(method, path, headers=H(admin))
                check(f"{method} {path.split('?')[0]} -> {r.status_code}", r.status_code not in (401, 403), r.text[:120])
            print("3. Sensitive actions are audited")
            db.expire_all()
            acts = {a for (a,) in db.query(AuditLog.action).filter(AuditLog.company_id == cid, AuditLog.user_id == admin.id,
                                                                   AuditLog.action.in_(("data.exported", "security_log.purged")))}
            check("data export audited", "data.exported" in acts, acts)
            check("security log clean-up audited", "security_log.purged" in acts, acts)
    finally:
        # the audit entries this test caused are kept: the audit log is append-only
        db.delete(nobody); db.flush(); db.delete(role); db.commit(); db.close()
    print("RESULT", "PASS" if not failures else f"FAIL ({', '.join(failures)})")
    return not failures


sys.exit(0 if main() else 1)
