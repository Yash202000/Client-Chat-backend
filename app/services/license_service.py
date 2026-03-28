"""License Service for On-Premise deployments.

Handles license key generation, validation, and management.
Uses HMAC-SHA256 signed JWT-style tokens for offline validation.
"""

import base64
import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.instance_license import InstanceLicense
from app.models.user import User
from app.models.company import Company
from app.schemas.license import (
    LicensePayload,
    LicenseStatusResponse,
)


def _get_secret_key() -> bytes:
    """Get the HMAC secret key for license signing/verification."""
    secret = settings.LICENSE_KEY_SECRET
    if not secret:
        raise ValueError("LICENSE_KEY_SECRET is not configured")
    return secret.encode('utf-8')


def _base64url_encode(data: bytes) -> str:
    """Base64 URL-safe encoding without padding."""
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('utf-8')


def _base64url_decode(data: str) -> bytes:
    """Base64 URL-safe decoding with padding restoration."""
    padding = 4 - len(data) % 4
    if padding != 4:
        data += '=' * padding
    return base64.urlsafe_b64decode(data.encode('utf-8'))


def generate_license_key(
    instance_name: str,
    max_users: int,
    max_companies: Optional[int] = None,
    features: list[str] = None,
    expires_in_days: int = 365,
) -> tuple[str, LicensePayload]:
    """
    Generate a new license key with HMAC-SHA256 signature.

    Returns a tuple of (license_key, payload).
    """
    if features is None:
        features = []

    now = int(time.time())
    expires_at = now + (expires_in_days * 24 * 60 * 60)

    payload = LicensePayload(
        instance_name=instance_name,
        max_users=max_users,
        max_companies=max_companies,
        features=features,
        expires_at=expires_at,
        issued_at=now,
        iss="HeyGenAlly License Authority",
    )

    # Create the payload JSON
    payload_json = payload.model_dump_json()
    payload_b64 = _base64url_encode(payload_json.encode('utf-8'))

    # Create HMAC signature
    secret = _get_secret_key()
    signature = hmac.new(secret, payload_b64.encode('utf-8'), hashlib.sha256).digest()
    signature_b64 = _base64url_encode(signature)

    # Combine into final license key
    license_key = f"{payload_b64}.{signature_b64}"

    return license_key, payload


def validate_license_key(license_key: str) -> Optional[LicensePayload]:
    """
    Validate a license key's signature.

    Returns the payload if valid, None if invalid signature.
    Does NOT check expiry - use is_license_expired() for that.
    """
    if not license_key:
        return None

    try:
        parts = license_key.split('.')
        if len(parts) != 2:
            return None

        payload_b64, signature_b64 = parts

        # Verify signature
        secret = _get_secret_key()
        expected_signature = hmac.new(secret, payload_b64.encode('utf-8'), hashlib.sha256).digest()
        actual_signature = _base64url_decode(signature_b64)

        if not hmac.compare_digest(expected_signature, actual_signature):
            return None

        # Decode payload
        payload_json = _base64url_decode(payload_b64).decode('utf-8')
        payload_data = json.loads(payload_json)

        return LicensePayload(**payload_data)

    except Exception:
        return None


def parse_license_key(license_key: str) -> Optional[LicensePayload]:
    """
    Parse a license key without verifying signature.
    Useful for displaying license info without validation.
    """
    if not license_key:
        return None

    try:
        parts = license_key.split('.')
        if len(parts) != 2:
            return None

        payload_b64 = parts[0]
        payload_json = _base64url_decode(payload_b64).decode('utf-8')
        payload_data = json.loads(payload_json)

        return LicensePayload(**payload_data)

    except Exception:
        return None


def is_license_expired(payload: LicensePayload) -> bool:
    """Check if a license payload has expired."""
    return int(time.time()) > payload.expires_at


def is_license_valid(license_key: str) -> bool:
    """
    Full license validation: signature + expiry check.

    Returns True if license is valid and not expired.
    """
    payload = validate_license_key(license_key)
    if not payload:
        return False

    return not is_license_expired(payload)


def get_license_user_limit(license_key: str) -> Optional[int]:
    """Get max_users from license key."""
    payload = validate_license_key(license_key)
    if not payload:
        return None
    return payload.max_users


def get_license_company_limit(license_key: str) -> Optional[int]:
    """Get max_companies from license key (None means unlimited)."""
    payload = validate_license_key(license_key)
    if not payload:
        return None
    return payload.max_companies


def has_feature(license_key: str, feature: str) -> bool:
    """Check if a specific feature is enabled in the license."""
    payload = validate_license_key(license_key)
    if not payload:
        return False
    return feature in payload.features


def get_total_user_count(db: Session) -> int:
    """Count all active users across ALL companies (instance-wide)."""
    return db.query(User).filter(User.is_active == True).count()


def get_total_company_count(db: Session) -> int:
    """Count all companies in the instance."""
    return db.query(Company).count()


# Database operations for InstanceLicense

def get_instance_license(db: Session) -> Optional[InstanceLicense]:
    """Get the singleton instance license record."""
    return db.query(InstanceLicense).filter(InstanceLicense.id == 1).first()


def activate_license(db: Session, license_key: str) -> tuple[bool, str, Optional[LicensePayload]]:
    """
    Activate a license key for this instance.

    Returns (success, message, payload).
    """
    # Validate the license key
    payload = validate_license_key(license_key)
    if not payload:
        return False, "Invalid license key signature", None

    if is_license_expired(payload):
        return False, "License key has expired", None

    # Get or create the instance license record
    instance_license = get_instance_license(db)
    if not instance_license:
        instance_license = InstanceLicense(id=1)
        db.add(instance_license)

    # Update the license
    now = datetime.utcnow()
    instance_license.license_key = license_key
    instance_license.activated_at = now
    instance_license.last_validated_at = now
    instance_license.license_metadata = payload.model_dump()
    instance_license.updated_at = now

    db.commit()
    db.refresh(instance_license)

    return True, "License activated successfully", payload


def get_license_status(db: Session) -> LicenseStatusResponse:
    """
    Get the current license status for the instance.

    Works in both cloud and on-premise modes.
    Checks both .env LICENSE_KEY and database for activated license.
    """
    if settings.DEPLOYMENT_MODE != "on_premise":
        # Cloud mode - return cloud status
        return LicenseStatusResponse(
            mode="cloud",
            status="active",
            features=["all"],  # All features available in cloud
        )

    # On-premise mode - check .env first, then database
    license_key = settings.LICENSE_KEY
    activated_at = None

    if not license_key:
        # Check database for activated license
        instance_license = get_instance_license(db)
        if instance_license and instance_license.license_key:
            license_key = instance_license.license_key
            activated_at = instance_license.activated_at

    if not license_key:
        return LicenseStatusResponse(
            mode="on_premise",
            status="not_activated",
            features=[],
        )

    # Validate the license
    payload = validate_license_key(license_key)
    if not payload:
        return LicenseStatusResponse(
            mode="on_premise",
            status="invalid",
            features=[],
        )

    # Check expiry
    if is_license_expired(payload):
        return LicenseStatusResponse(
            mode="on_premise",
            status="expired",
            instance_name=payload.instance_name,
            max_users=payload.max_users,
            max_companies=payload.max_companies,
            features=payload.features,
            expires_at=datetime.fromtimestamp(payload.expires_at),
            days_until_expiry=0,
            activated_at=activated_at,
        )

    # License is valid
    current_user_count = get_total_user_count(db)
    current_company_count = get_total_company_count(db)
    expires_at = datetime.fromtimestamp(payload.expires_at)
    days_until_expiry = (expires_at - datetime.utcnow()).days

    return LicenseStatusResponse(
        mode="on_premise",
        status="active",
        instance_name=payload.instance_name,
        max_users=payload.max_users,
        max_companies=payload.max_companies,
        current_user_count=current_user_count,
        current_company_count=current_company_count,
        users_remaining=max(0, payload.max_users - current_user_count),
        features=payload.features,
        expires_at=expires_at,
        days_until_expiry=max(0, days_until_expiry),
        activated_at=activated_at,
    )


def can_add_user_on_premise(db: Session) -> bool:
    """
    Check if the on-premise instance can add more users.
    Checks instance-wide user limit across ALL companies.
    """
    if settings.DEPLOYMENT_MODE != "on_premise":
        return True  # Cloud mode uses per-company limits

    # Get the active license
    license_key = settings.LICENSE_KEY
    if not license_key:
        instance_license = get_instance_license(db)
        if instance_license:
            license_key = instance_license.license_key

    if not license_key or not is_license_valid(license_key):
        return False

    max_users = get_license_user_limit(license_key)
    if max_users is None:
        return False

    current_users = get_total_user_count(db)
    return current_users < max_users


def can_add_company_on_premise(db: Session) -> bool:
    """
    Check if the on-premise instance can add more companies.
    Returns True if no company limit is set.
    """
    if settings.DEPLOYMENT_MODE != "on_premise":
        return True

    # Get the active license
    license_key = settings.LICENSE_KEY
    if not license_key:
        instance_license = get_instance_license(db)
        if instance_license:
            license_key = instance_license.license_key

    if not license_key or not is_license_valid(license_key):
        return False

    max_companies = get_license_company_limit(license_key)
    if max_companies is None:
        return True  # No company limit set

    current_companies = get_total_company_count(db)
    return current_companies < max_companies
