#!/usr/bin/env python3
"""
Generate a license key for on-premise deployments.

Usage:
    python scripts/generate_license.py --instance "Acme Corp" --users 50 --days 365
    python scripts/generate_license.py --instance "Test" --users 10 --hours 2
    python scripts/generate_license.py --instance "Quick Test" --users 5 --minutes 30

The script will output the license key that you can put in your .env file.
"""

import argparse
import sys
import os

# Add the backend app to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta


def generate_license(
    secret: str,
    instance_name: str,
    max_users: int,
    max_companies: int | None = None,
    features: list[str] | None = None,
    expires_in_seconds: int = 365 * 24 * 60 * 60,
) -> str:
    """Generate a license key using the license service logic."""
    import base64
    import hashlib
    import hmac
    import json
    import time

    if features is None:
        features = []

    now = int(time.time())
    expires_at = now + expires_in_seconds

    payload = {
        "instance_name": instance_name,
        "max_users": max_users,
        "max_companies": max_companies,
        "features": features,
        "expires_at": expires_at,
        "issued_at": now,
        "iss": "HeyGenAlly License Authority",
    }

    # Base64 URL-safe encoding
    def b64_encode(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b'=').decode('utf-8')

    payload_json = json.dumps(payload)
    payload_b64 = b64_encode(payload_json.encode('utf-8'))

    # Create HMAC signature
    signature = hmac.new(
        secret.encode('utf-8'),
        payload_b64.encode('utf-8'),
        hashlib.sha256
    ).digest()
    signature_b64 = b64_encode(signature)

    license_key = f"{payload_b64}.{signature_b64}"

    return license_key, payload


def main():
    parser = argparse.ArgumentParser(description="Generate an HeyGenAlly license key")
    parser.add_argument("--secret", type=str, help="HMAC secret key (or set LICENSE_KEY_SECRET env var)")
    parser.add_argument("--instance", type=str, required=True, help="Instance name (e.g., 'Acme Corp Production')")
    parser.add_argument("--users", type=int, default=50, help="Maximum users allowed (default: 50)")
    parser.add_argument("--companies", type=int, default=None, help="Maximum companies allowed (default: unlimited)")
    parser.add_argument("--features", type=str, nargs="*", default=[], help="Enabled features (e.g., workflows api_access voice_calls)")

    # Time duration options (mutually exclusive priority: minutes > hours > days)
    time_group = parser.add_argument_group("validity duration (choose one)")
    time_group.add_argument("--days", type=int, default=None, help="License validity in days (default: 365)")
    time_group.add_argument("--hours", type=int, default=None, help="License validity in hours")
    time_group.add_argument("--minutes", type=int, default=None, help="License validity in minutes")

    args = parser.parse_args()

    # Get secret from args or environment
    secret = args.secret or os.environ.get("LICENSE_KEY_SECRET")
    if not secret:
        print("Error: LICENSE_KEY_SECRET not provided. Use --secret or set LICENSE_KEY_SECRET env var.")
        print("\nTo generate a random secret, run:")
        print("  python -c \"import secrets; print(secrets.token_urlsafe(32))\"")
        sys.exit(1)

    # Calculate expiry in seconds (priority: minutes > hours > days)
    if args.minutes is not None:
        expires_in_seconds = args.minutes * 60
        duration_str = f"{args.minutes} minutes"
    elif args.hours is not None:
        expires_in_seconds = args.hours * 60 * 60
        duration_str = f"{args.hours} hours"
    else:
        days = args.days if args.days is not None else 365
        expires_in_seconds = days * 24 * 60 * 60
        duration_str = f"{days} days"

    license_key, payload = generate_license(
        secret=secret,
        instance_name=args.instance,
        max_users=args.users,
        max_companies=args.companies,
        features=args.features,
        expires_in_seconds=expires_in_seconds,
    )

    expires_date = datetime.fromtimestamp(payload["expires_at"])

    print("\n# " + "=" * 60)
    print("# LICENSE KEY GENERATED")
    print("# " + "=" * 60)
    print(f"\n# Instance:    {payload['instance_name']}")
    print(f"# Max Users:   {payload['max_users']}")
    print(f"# Max Companies: {payload['max_companies'] or 'Unlimited'}")
    print(f"# Features:    {', '.join(payload['features']) or 'None'}")
    print(f"# Expires:     {expires_date.strftime('%Y-%m-%d %H:%M:%S')} ({duration_str})")
    print(f"\n# " + "-" * 60)
    print("# Add these to your .env file:")
    print("# " + "-" * 60)
    print(f"\nDEPLOYMENT_MODE=on_premise")
    print(f"LICENSE_KEY_SECRET={secret}")
    print(f"LICENSE_KEY={license_key}")
    print("\n# " + "=" * 60)


if __name__ == "__main__":
    main()
