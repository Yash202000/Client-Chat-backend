#!/usr/bin/env python3
"""
Interactive Chat Script for API Channel

This script allows you to chat with your AgentConnect agent via the API channel.
It simulates a third-party integration using the REST API.

Usage:
    python scripts/api_channel_chat.py --api-key YOUR_API_KEY [--base-url http://localhost:8000]

Example:
    python scripts/api_channel_chat.py --api-key ak_abc123xyz

Commands during chat:
    /quit, /exit    - Exit the chat
    /clear          - Clear current session and start new
    /session        - Show current session info
    /history        - Show message history
    /help           - Show available commands
"""

import argparse
import requests
import json
import sys
import uuid
from datetime import datetime
from typing import Optional

# ANSI color codes for terminal output
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    DIM = '\033[2m'


def print_colored(text: str, color: str = Colors.ENDC):
    """Print text with color."""
    print(f"{color}{text}{Colors.ENDC}")


def print_header():
    """Print the chat header."""
    print_colored("\n" + "=" * 60, Colors.CYAN)
    print_colored("   AgentConnect API Channel - Interactive Chat", Colors.BOLD + Colors.CYAN)
    print_colored("=" * 60, Colors.CYAN)
    print_colored("Type /help for available commands\n", Colors.DIM)


def print_help():
    """Print available commands."""
    print_colored("\nAvailable Commands:", Colors.YELLOW)
    print("  /quit, /exit  - Exit the chat")
    print("  /clear        - Clear session and start new conversation")
    print("  /session      - Show current session info")
    print("  /history      - Show message history")
    print("  /toggle-ai    - Toggle AI responses on/off")
    print("  /help         - Show this help message")
    print()


class APIChannelChat:
    """Interactive chat client for the API Channel."""

    def __init__(self, base_url: str, api_key: str, user_id: Optional[str] = None):
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.user_id = user_id or f"cli_user_{uuid.uuid4().hex[:8]}"
        self.session_id: Optional[str] = None
        self.ai_enabled = True

        self.headers = {
            "X-API-Key": api_key,
            "Content-Type": "application/json"
        }

    def send_message(self, message: str) -> dict:
        """Send a message to the API channel."""
        url = f"{self.base_url}/api/v1/external/message"

        payload = {
            "message": message,
            "external_user_id": self.user_id,
            "response_mode": "sync"  # Wait for response
        }

        try:
            response = requests.post(url, headers=self.headers, json=payload, timeout=60)
            response.raise_for_status()
            data = response.json()
            self.session_id = data.get("session_id")
            return data
        except requests.exceptions.Timeout:
            return {"error": "Request timed out. The agent might be taking too long to respond."}
        except requests.exceptions.HTTPError as e:
            try:
                error_detail = e.response.json().get("detail", str(e))
            except:
                error_detail = str(e)
            return {"error": f"HTTP Error: {error_detail}"}
        except requests.exceptions.RequestException as e:
            return {"error": f"Request failed: {str(e)}"}

    def create_session(self) -> dict:
        """Create a new session."""
        url = f"{self.base_url}/api/v1/external/sessions"

        payload = {
            "external_user_id": self.user_id,
            "contact_name": f"CLI User {self.user_id[:8]}"
        }

        try:
            response = requests.post(url, headers=self.headers, json=payload, timeout=30)
            response.raise_for_status()
            data = response.json()
            self.session_id = data.get("session_id")
            return data
        except requests.exceptions.RequestException as e:
            return {"error": str(e)}

    def get_session_info(self) -> dict:
        """Get current session information."""
        if not self.session_id:
            return {"error": "No active session"}

        url = f"{self.base_url}/api/v1/external/sessions/{self.session_id}"

        try:
            response = requests.get(url, headers=self.headers, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            return {"error": str(e)}

    def get_history(self, limit: int = 20) -> dict:
        """Get message history."""
        if not self.session_id:
            return {"error": "No active session"}

        url = f"{self.base_url}/api/v1/external/messages/{self.session_id}?limit={limit}"

        try:
            response = requests.get(url, headers=self.headers, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            return {"error": str(e)}

    def toggle_ai(self) -> dict:
        """Toggle AI responses on/off."""
        if not self.session_id:
            return {"error": "No active session"}

        self.ai_enabled = not self.ai_enabled
        url = f"{self.base_url}/api/v1/external/sessions/{self.session_id}/ai?enabled={str(self.ai_enabled).lower()}"

        try:
            response = requests.post(
                url,
                headers=self.headers,
                timeout=30
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            return {"error": str(e)}

    def close_session(self) -> dict:
        """Close the current session."""
        if not self.session_id:
            return {"error": "No active session"}

        url = f"{self.base_url}/api/v1/external/sessions/{self.session_id}/close"

        try:
            response = requests.post(url, headers=self.headers, json={}, timeout=30)
            response.raise_for_status()
            data = response.json()
            self.session_id = None
            return data
        except requests.exceptions.RequestException as e:
            return {"error": str(e)}

    def clear_session(self):
        """Clear the current session and start fresh."""
        if self.session_id:
            self.close_session()
        self.user_id = f"cli_user_{uuid.uuid4().hex[:8]}"
        self.session_id = None


def run_chat(base_url: str, api_key: str, user_id: Optional[str] = None):
    """Run the interactive chat loop."""
    print_header()

    chat = APIChannelChat(base_url, api_key, user_id)

    print_colored(f"User ID: {chat.user_id}", Colors.DIM)
    print_colored(f"API URL: {base_url}", Colors.DIM)
    print()

    while True:
        try:
            # Get user input
            user_input = input(f"{Colors.GREEN}You: {Colors.ENDC}").strip()

            if not user_input:
                continue

            # Handle commands
            if user_input.startswith('/'):
                command = user_input.lower()

                if command in ['/quit', '/exit']:
                    print_colored("\nGoodbye! Session closed.", Colors.CYAN)
                    if chat.session_id:
                        chat.close_session()
                    break

                elif command == '/help':
                    print_help()
                    continue

                elif command == '/clear':
                    chat.clear_session()
                    print_colored("Session cleared. Starting fresh conversation.", Colors.YELLOW)
                    print_colored(f"New User ID: {chat.user_id}", Colors.DIM)
                    continue

                elif command == '/session':
                    info = chat.get_session_info()
                    if "error" in info:
                        print_colored(f"Error: {info['error']}", Colors.RED)
                    else:
                        print_colored("\nSession Info:", Colors.YELLOW)
                        print(json.dumps(info, indent=2, default=str))
                    continue

                elif command == '/history':
                    history = chat.get_history()
                    if "error" in history:
                        print_colored(f"Error: {history['error']}", Colors.RED)
                    else:
                        messages = history.get("messages", [])
                        print_colored(f"\nMessage History ({len(messages)} messages):", Colors.YELLOW)
                        for msg in messages:
                            sender = msg.get("sender", "unknown")
                            content = msg.get("message", "")[:100]
                            timestamp = msg.get("timestamp", "")[:19]
                            color = Colors.GREEN if sender == "user" else Colors.BLUE
                            print(f"  {color}[{timestamp}] {sender}: {content}{Colors.ENDC}")
                    continue

                elif command == '/toggle-ai':
                    result = chat.toggle_ai()
                    if "error" in result:
                        print_colored(f"Error: {result['error']}", Colors.RED)
                    else:
                        status = "enabled" if chat.ai_enabled else "disabled"
                        print_colored(f"AI responses {status}", Colors.YELLOW)
                    continue

                else:
                    print_colored(f"Unknown command: {command}. Type /help for available commands.", Colors.RED)
                    continue

            # Send message to API
            print_colored("Sending...", Colors.DIM)

            result = chat.send_message(user_input)

            if "error" in result:
                print_colored(f"\nError: {result['error']}", Colors.RED)
            else:
                # API returns response_message field
                response = result.get("response_message") or result.get("response", "")
                response_type = result.get("response_type", "text")
                options = result.get("options", [])
                options_text = result.get("options_text", "")

                # Clear the "Sending..." line and print response
                print(f"\033[A\033[K", end="")  # Move up and clear line

                if response:
                    print_colored(f"Agent: {response}", Colors.BLUE)
                else:
                    print_colored("Agent: (no response)", Colors.DIM)

                # Show options if this is a prompt
                if response_type == "prompt" and (options or options_text):
                    if options_text:
                        print_colored(f"  Options: {options_text}", Colors.YELLOW)
                    elif options:
                        # Format options from list
                        opt_labels = []
                        for opt in options:
                            if isinstance(opt, dict):
                                opt_labels.append(opt.get("value") or opt.get("key", str(opt)))
                            else:
                                opt_labels.append(str(opt))
                        print_colored(f"  Options: {', '.join(opt_labels)}", Colors.YELLOW)

                # Show session ID on first message
                if chat.session_id and result.get("session_id"):
                    print_colored(f"  [Session: {chat.session_id[:30]}...]", Colors.DIM)

        except KeyboardInterrupt:
            print_colored("\n\nInterrupted. Goodbye!", Colors.CYAN)
            if chat.session_id:
                chat.close_session()
            break
        except EOFError:
            print_colored("\n\nEOF. Goodbye!", Colors.CYAN)
            if chat.session_id:
                chat.close_session()
            break


def validate_connection(base_url: str, api_key: str) -> bool:
    """Validate the API connection before starting chat."""
    print_colored("Validating API connection...", Colors.DIM)

    url = f"{base_url.rstrip('/')}/api/v1/external/sessions"
    headers = {
        "X-API-Key": api_key,
        "Content-Type": "application/json"
    }

    try:
        # Try to create a test session
        response = requests.post(
            url,
            headers=headers,
            json={"external_user_id": "connection_test"},
            timeout=10
        )

        if response.status_code == 401:
            print_colored("Error: Invalid API key", Colors.RED)
            return False
        elif response.status_code == 404:
            print_colored("Error: No API integration configured for this key", Colors.RED)
            print_colored("Please create an API Integration in the Settings > API Channel tab", Colors.YELLOW)
            return False
        elif response.status_code == 400:
            detail = response.json().get("detail", "")
            if "not active" in detail.lower():
                print_colored("Error: API integration is not active", Colors.RED)
                return False
        elif response.status_code in [200, 201]:
            print_colored("Connection successful!", Colors.GREEN)
            return True
        else:
            print_colored(f"Unexpected response: {response.status_code}", Colors.YELLOW)
            # Try anyway
            return True

    except requests.exceptions.ConnectionError:
        print_colored(f"Error: Cannot connect to {base_url}", Colors.RED)
        print_colored("Make sure the server is running", Colors.YELLOW)
        return False
    except requests.exceptions.Timeout:
        print_colored("Error: Connection timed out", Colors.RED)
        return False
    except Exception as e:
        print_colored(f"Error: {str(e)}", Colors.RED)
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Interactive chat with AgentConnect API Channel",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python scripts/api_channel_chat.py --api-key ak_your_key_here
    python scripts/api_channel_chat.py --api-key ak_your_key --base-url https://api.example.com
    python scripts/api_channel_chat.py --api-key ak_your_key --user-id my_user_123
        """
    )

    parser.add_argument(
        "--api-key", "-k",
        required=True,
        help="Your API key (starts with 'ak_')"
    )

    parser.add_argument(
        "--base-url", "-u",
        default="http://localhost:8000",
        help="Base URL of the AgentConnect API (default: http://localhost:8000)"
    )

    parser.add_argument(
        "--user-id", "-i",
        default=None,
        help="Optional custom user ID for the session"
    )

    parser.add_argument(
        "--no-validate",
        action="store_true",
        help="Skip connection validation"
    )

    args = parser.parse_args()

    # Validate API key format
    if not args.api_key.startswith("ak_"):
        print_colored("Warning: API key should start with 'ak_'", Colors.YELLOW)

    # Validate connection
    if not args.no_validate:
        if not validate_connection(args.base_url, args.api_key):
            sys.exit(1)

    # Start chat
    run_chat(args.base_url, args.api_key, args.user_id)


if __name__ == "__main__":
    main()
