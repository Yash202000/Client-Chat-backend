"""
Two-Factor Authentication service (TOTP via RFC 6238).

Uses pyotp for secret generation and code verification.
QR code is returned as a base64-encoded PNG for the frontend to render inline.
"""
import base64
import io
import logging
import pyotp
import qrcode

logger = logging.getLogger(__name__)

ISSUER_NAME = "HeyGenAlly"


def generate_totp_secret() -> str:
    return pyotp.random_base32()


def get_provisioning_uri(secret: str, email: str) -> str:
    totp = pyotp.TOTP(secret)
    return totp.provisioning_uri(name=email, issuer_name=ISSUER_NAME)


def get_qr_code_base64(provisioning_uri: str) -> str:
    img = qrcode.make(provisioning_uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def verify_totp_code(secret: str, code: str) -> bool:
    totp = pyotp.TOTP(secret)
    # valid_window=1 accepts one period before/after for clock drift
    return totp.verify(code, valid_window=1)
