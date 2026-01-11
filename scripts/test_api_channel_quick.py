#!/usr/bin/env python3
"""
Quick Test Script for API Channel

This script performs a quick smoke test of the API Channel functionality.
It creates a session, sends a test message, and verifies the response.

Usage:
    python scripts/test_api_channel_quick.py --api-key YOUR_API_KEY
"""

import argparse
import requests
import json
import sys
from datetime import datetime


def test_api_channel(base_url: str, api_key: str) -> bool:
    """Run quick tests on the API channel."""
    headers = {
        "X-API-Key": api_key,
        "Content-Type": "application/json"
    }

    test_user_id = f"test_user_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    results = []

    print(f"\n{'='*60}")
    print("API Channel Quick Test")
    print(f"{'='*60}")
    print(f"Base URL: {base_url}")
    print(f"Test User ID: {test_user_id}")
    print(f"{'='*60}\n")

    # Test 1: Create Session
    print("Test 1: Create Session")
    print("-" * 40)
    try:
        response = requests.post(
            f"{base_url}/api/v1/external/sessions",
            headers=headers,
            json={
                "external_user_id": test_user_id,
                "contact_name": "Quick Test User"
            },
            timeout=30
        )

        if response.status_code in [200, 201]:
            data = response.json()
            session_id = data.get("session_id")
            print(f"  Status: PASS")
            print(f"  Session ID: {session_id}")
            results.append(("Create Session", True))
        else:
            print(f"  Status: FAIL")
            print(f"  Response: {response.status_code} - {response.text[:200]}")
            results.append(("Create Session", False))
            session_id = None
    except Exception as e:
        print(f"  Status: FAIL")
        print(f"  Error: {str(e)}")
        results.append(("Create Session", False))
        session_id = None

    print()

    # Test 2: Send Message
    print("Test 2: Send Message (Sync)")
    print("-" * 40)
    try:
        response = requests.post(
            f"{base_url}/api/v1/external/message",
            headers=headers,
            json={
                "message": "Hello, this is a test message!",
                "external_user_id": test_user_id,
                "response_mode": "sync"
            },
            timeout=60
        )

        if response.status_code == 200:
            data = response.json()
            print(f"  Status: PASS")
            print(f"  Session: {data.get('session_id', 'N/A')}")
            print(f"  Response Type: {data.get('response_type', 'N/A')}")
            agent_response = data.get("response_message") or data.get("response", "")
            print(f"  Agent Response: {agent_response[:100] if agent_response else '(empty)'}{'...' if agent_response and len(agent_response) > 100 else ''}")
            results.append(("Send Message", True))
            session_id = data.get("session_id") or session_id
        else:
            print(f"  Status: FAIL")
            print(f"  Response: {response.status_code} - {response.text[:200]}")
            results.append(("Send Message", False))
    except Exception as e:
        print(f"  Status: FAIL")
        print(f"  Error: {str(e)}")
        results.append(("Send Message", False))

    print()

    # Test 3: Get Session Info
    if session_id:
        print("Test 3: Get Session Info")
        print("-" * 40)
        try:
            response = requests.get(
                f"{base_url}/api/v1/external/sessions/{session_id}",
                headers=headers,
                timeout=30
            )

            if response.status_code == 200:
                data = response.json()
                print(f"  Status: PASS")
                print(f"  Session Status: {data.get('status', 'N/A')}")
                print(f"  Channel: {data.get('channel', 'N/A')}")
                results.append(("Get Session Info", True))
            else:
                print(f"  Status: FAIL")
                print(f"  Response: {response.status_code}")
                results.append(("Get Session Info", False))
        except Exception as e:
            print(f"  Status: FAIL")
            print(f"  Error: {str(e)}")
            results.append(("Get Session Info", False))

        print()

    # Test 4: Get Message History
    if session_id:
        print("Test 4: Get Message History")
        print("-" * 40)
        try:
            response = requests.get(
                f"{base_url}/api/v1/external/messages/{session_id}",
                headers=headers,
                timeout=30
            )

            if response.status_code == 200:
                data = response.json()
                messages = data.get("messages", [])
                print(f"  Status: PASS")
                print(f"  Message Count: {len(messages)}")
                results.append(("Get Message History", True))
            else:
                print(f"  Status: FAIL")
                print(f"  Response: {response.status_code}")
                results.append(("Get Message History", False))
        except Exception as e:
            print(f"  Status: FAIL")
            print(f"  Error: {str(e)}")
            results.append(("Get Message History", False))

        print()

    # Test 5: Close Session
    if session_id:
        print("Test 5: Close Session")
        print("-" * 40)
        try:
            response = requests.post(
                f"{base_url}/api/v1/external/sessions/{session_id}/close",
                headers=headers,
                json={},  # Empty body is accepted
                timeout=30
            )

            if response.status_code == 200:
                print(f"  Status: PASS")
                print(f"  Session closed successfully")
                results.append(("Close Session", True))
            else:
                print(f"  Status: FAIL")
                print(f"  Response: {response.status_code}")
                results.append(("Close Session", False))
        except Exception as e:
            print(f"  Status: FAIL")
            print(f"  Error: {str(e)}")
            results.append(("Close Session", False))

        print()

    # Summary
    print(f"{'='*60}")
    print("Test Summary")
    print(f"{'='*60}")

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for test_name, result in results:
        status = "PASS" if result else "FAIL"
        symbol = "✓" if result else "✗"
        print(f"  {symbol} {test_name}: {status}")

    print(f"\nTotal: {passed}/{total} tests passed")
    print(f"{'='*60}\n")

    return passed == total


def main():
    parser = argparse.ArgumentParser(description="Quick test for API Channel")

    parser.add_argument(
        "--api-key", "-k",
        required=True,
        help="Your API key"
    )

    parser.add_argument(
        "--base-url", "-u",
        default="http://localhost:8000",
        help="Base URL of the API (default: http://localhost:8000)"
    )

    args = parser.parse_args()

    success = test_api_channel(args.base_url, args.api_key)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
