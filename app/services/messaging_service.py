import httpx
import logging
from typing import Dict, Any, List, Union, Optional

from sqlalchemy.orm import Session

from app.models.integration import Integration
from app.services import integration_service
from app.services.whatsapp_token_service import whatsapp_token_service

logger = logging.getLogger(__name__)

WHATSAPP_API_VERSION = "v19.0"


async def send_whatsapp_message(
    recipient_phone_number: str,
    message_text: str,
    integration: Integration,
    db: Optional[Session] = None
) -> Dict[str, Any]:
    """
    Sends a text message to a WhatsApp user via the Meta Cloud API.

    If a database session is provided and OAuth is configured,
    the token will be automatically refreshed if needed.

    Args:
        recipient_phone_number: The recipient's WhatsApp phone number
        message_text: The message text to send
        integration: The WhatsApp integration
        db: Optional database session for token refresh
    """
    credentials = integration_service.get_decrypted_credentials(integration)
    phone_number_id = credentials.get("phone_number_id")

    # Get a valid token (with automatic refresh if OAuth is enabled and db provided)
    if db:
        api_token = await whatsapp_token_service.ensure_valid_token(db, integration)
    else:
        # Fallback to stored token without refresh
        api_token = credentials.get("api_token") or credentials.get("access_token")

    if not api_token or not phone_number_id:
        raise ValueError("WhatsApp credentials (api_token, phone_number_id) are not configured for this integration.")

    url = f"https://graph.facebook.com/{WHATSAPP_API_VERSION}/{phone_number_id}/messages"
    
    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
    }
    
    payload = {
        "messaging_product": "whatsapp",
        "to": recipient_phone_number,
        "type": "text",
        "text": {
            "preview_url": False,
            "body": message_text
        }
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()  # Raises an exception for 4XX/5XX responses
            print(f"Successfully sent message to {recipient_phone_number}. Response: {response.json()}")
            return response.json()
        except httpx.HTTPStatusError as e:
            print(f"Error sending WhatsApp message: {e.response.text}")
            # Re-raise the exception so the caller can handle it
            raise e
        except Exception as e:
            print(f"An unexpected error occurred: {e}")
            raise e

async def send_whatsapp_interactive_message(
    recipient_phone_number: str,
    message_text: str,
    options: List[Union[str, Dict[str, str]]],
    integration: Integration,
    db: Optional[Session] = None
) -> Dict[str, Any]:
    """
    Sends an interactive message to a WhatsApp user.
    - Uses button format for 1-3 options (max 20 chars per button title)
    - Uses list format for 4-10 options (max 24 chars per row title)
    - Truncates to 10 options if more are provided

    Supports both string options (legacy) and key-value dict options (new).

    If a database session is provided and OAuth is configured,
    the token will be automatically refreshed if needed.

    Args:
        recipient_phone_number: The recipient's WhatsApp phone number
        message_text: The message text to send
        options: List of button options (strings or dicts with key/value)
        integration: The WhatsApp integration
        db: Optional database session for token refresh
    """
    credentials = integration_service.get_decrypted_credentials(integration)
    phone_number_id = credentials.get("phone_number_id")

    # Get a valid token (with automatic refresh if OAuth is enabled and db provided)
    if db:
        api_token = await whatsapp_token_service.ensure_valid_token(db, integration)
    else:
        # Fallback to stored token without refresh
        api_token = credentials.get("api_token") or credentials.get("access_token")

    if not api_token or not phone_number_id:
        raise ValueError("WhatsApp credentials (api_token, phone_number_id) are not configured for this integration.")

    url = f"https://graph.facebook.com/{WHATSAPP_API_VERSION}/{phone_number_id}/messages"

    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
    }

    # Filter out empty options
    valid_options = [opt for opt in options if opt]

    # Warn if more than 10 options (WhatsApp list max)
    if len(valid_options) > 10:
        print(f"Warning: WhatsApp supports max 10 list options. Truncating from {len(valid_options)} to 10.")
        valid_options = valid_options[:10]

    # Determine message type based on option count
    if len(valid_options) <= 3:
        # Use button format for 1-3 options
        buttons = []
        for i, option in enumerate(valid_options):
            if isinstance(option, dict):
                button_id = str(option.get("key", f"option_{i+1}"))[:200]
                button_title = str(option.get("value", ""))[:20]
            else:
                button_id = str(option)[:200]
                button_title = str(option)[:20]

            buttons.append({
                "type": "reply",
                "reply": {
                    "id": button_id,
                    "title": button_title
                }
            })

        payload = {
            "messaging_product": "whatsapp",
            "to": recipient_phone_number,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {
                    "text": message_text
                },
                "action": {
                    "buttons": buttons
                }
            }
        }
    else:
        # Use list format for 4-10 options
        rows = []
        for i, option in enumerate(valid_options):
            if isinstance(option, dict):
                row_id = str(option.get("key", f"option_{i+1}"))[:200]
                row_title = str(option.get("value", ""))[:24]
            else:
                row_id = str(option)[:200]
                row_title = str(option)[:24]

            rows.append({
                "id": row_id,
                "title": row_title
            })

        payload = {
            "messaging_product": "whatsapp",
            "to": recipient_phone_number,
            "type": "interactive",
            "interactive": {
                "type": "list",
                "body": {
                    "text": message_text
                },
                "action": {
                    "button": "View Options",
                    "sections": [{
                        "title": "Options",
                        "rows": rows
                    }]
                }
            }
        }

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            msg_type = "list" if len(valid_options) > 3 else "button"
            print(f"Successfully sent {msg_type} interactive message to {recipient_phone_number}. Response: {response.json()}")
            return response.json()
        except httpx.HTTPStatusError as e:
            print(f"Error sending WhatsApp interactive message: {e.response.text}")
            raise e
        except Exception as e:
            print(f"An unexpected error occurred: {e}")
            raise e


async def download_whatsapp_media(
    media_id: str,
    integration: Integration,
    db: Optional[Session] = None
) -> Dict[str, Any]:
    """
    Downloads media from WhatsApp using the Media API.

    WhatsApp media download is a two-step process:
    1. GET the media URL from: https://graph.facebook.com/{api-version}/{media-id}
    2. Download the file from the returned URL

    Args:
        media_id: The WhatsApp media ID
        integration: The WhatsApp integration
        db: Optional database session for token refresh

    Returns:
        Dict with 'data' (bytes), 'mime_type', and 'file_name'
    """
    credentials = integration_service.get_decrypted_credentials(integration)

    # Get a valid token
    if db:
        api_token = await whatsapp_token_service.ensure_valid_token(db, integration)
    else:
        api_token = credentials.get("api_token") or credentials.get("access_token")

    if not api_token:
        raise ValueError("WhatsApp credentials (api_token) are not configured for this integration.")

    headers = {
        "Authorization": f"Bearer {api_token}",
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            # Step 1: Get media URL
            media_url_endpoint = f"https://graph.facebook.com/{WHATSAPP_API_VERSION}/{media_id}"
            response = await client.get(media_url_endpoint, headers=headers)
            response.raise_for_status()
            media_info = response.json()

            download_url = media_info.get("url")
            mime_type = media_info.get("mime_type", "application/octet-stream")

            if not download_url:
                raise ValueError(f"No download URL returned for media ID: {media_id}")

            print(f"[WhatsApp Media] Got download URL for media {media_id}, mime_type: {mime_type}")

            # Step 2: Download the actual file
            download_response = await client.get(download_url, headers=headers)
            download_response.raise_for_status()

            file_data = download_response.content

            # Generate filename based on mime type
            extension_map = {
                "image/jpeg": ".jpg",
                "image/png": ".png",
                "image/webp": ".webp",
                "image/gif": ".gif",
                "video/mp4": ".mp4",
                "video/3gpp": ".3gp",
                "audio/aac": ".aac",
                "audio/mp4": ".m4a",
                "audio/mpeg": ".mp3",
                "audio/amr": ".amr",
                "audio/ogg": ".ogg",
                "application/pdf": ".pdf",
                "application/vnd.ms-powerpoint": ".ppt",
                "application/msword": ".doc",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
                "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
            }
            extension = extension_map.get(mime_type, "")
            file_name = f"whatsapp_media_{media_id}{extension}"

            print(f"[WhatsApp Media] Downloaded {len(file_data)} bytes for {file_name}")

            return {
                "data": file_data,
                "mime_type": mime_type,
                "file_name": file_name
            }

        except httpx.HTTPStatusError as e:
            print(f"Error downloading WhatsApp media: {e.response.text}")
            raise e
        except Exception as e:
            print(f"An unexpected error occurred downloading media: {e}")
            raise e


async def send_instagram_or_messenger_message(
    recipient_id: str,
    message_text: str,
    integration: Integration,
    platform: str
) -> Dict[str, Any]:
    """
    Sends a text message to an Instagram or Messenger user via the Meta Graph API.
    """
    credentials = integration_service.get_decrypted_credentials(integration)
    page_access_token = credentials.get("page_access_token") or credentials.get("access_token")

    if not page_access_token:
        raise ValueError(f"{platform.capitalize()} credentials (page_access_token) are not configured for this integration.")

    url = f"https://graph.facebook.com/{WHATSAPP_API_VERSION}/me/messages"
    
    headers = {
        "Authorization": f"Bearer {page_access_token}",
        "Content-Type": "application/json",
    }
    
    payload = {
        "recipient": {"id": recipient_id},
        "message": {"text": message_text},
        "messaging_type": "RESPONSE"
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            print(f"Successfully sent {platform} message to {recipient_id}. Response: {response.json()}")
            return response.json()
        except httpx.HTTPStatusError as e:
            print(f"Error sending {platform} message: {e.response.text}")
            raise e
        except Exception as e:
            print(f"An unexpected error occurred: {e}")
            raise e

async def send_instagram_message(
    recipient_psid: str,
    message_text: str,
    integration: Integration
) -> Dict[str, Any]:
    """
    Sends a text message to an Instagram user.
    """
    return await send_instagram_or_messenger_message(recipient_psid, message_text, integration, "instagram")

async def send_messenger_message(
    recipient_psid: str,
    message_text: str,
    integration: Integration
) -> Dict[str, Any]:
    """
    Sends a text message to a Messenger user via the Meta Graph API.
    """
    return await send_instagram_or_messenger_message(recipient_psid, message_text, integration, "messenger")

async def send_gmail_message(
    recipient_email: str,
    subject: str,
    message_text: str,
    integration: Integration
) -> Dict[str, Any]:
    """
    Sends an email to a user via the Gmail API.
    NOTE: This is a placeholder and needs to be implemented with the Google API client library.
    """
    credentials = integration_service.get_decrypted_credentials(integration)
    # Actual implementation will require OAuth2 flow and Google API client
    print(f"Simulating sending email to {recipient_email} with subject '{subject}'")
    print(f"Message: {message_text}")
    return {"status": "simulated_success"}

async def send_meeting_link(
    channel: str,
    recipient_id: str,
    meeting_link: str,
    agent_name: str,
    integration: Integration,
    db: Optional[Session] = None
) -> Dict[str, Any]:
    """
    Send a meeting link to a customer via their messaging channel.

    Args:
        channel: The messaging channel (whatsapp, telegram, instagram, messenger)
        recipient_id: The recipient's ID (phone number, chat_id, etc.)
        meeting_link: The full meeting URL to share
        agent_name: Name of the agent for the message
        integration: The messaging integration
        db: Optional database session for token refresh

    Returns:
        Response from the messaging API
    """
    message = (
        f"🎥 {agent_name} is ready to assist you!\n\n"
        f"Join the meeting here:\n{meeting_link}\n\n"
        f"Tap the link above to start your video call."
    )

    if channel == 'whatsapp':
        return await send_whatsapp_message(recipient_id, message, integration, db)
    elif channel == 'telegram':
        return await send_telegram_message(int(recipient_id), message, integration)
    elif channel == 'instagram':
        return await send_instagram_message(recipient_id, message, integration)
    elif channel == 'messenger':
        return await send_messenger_message(recipient_id, message, integration)
    else:
        raise ValueError(f"Unsupported channel for meeting link: {channel}")


async def send_telegram_message(
    chat_id: int,
    message_text: str,
    integration: Integration
) -> Dict[str, Any]:
    """
    Sends a message to a Telegram user via the Telegram Bot API.
    """
    credentials = integration_service.get_decrypted_credentials(integration)
    bot_token = credentials.get("bot_token")

    if not bot_token:
        raise ValueError("Telegram credentials (bot_token) are not configured for this integration.")

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    
    payload = {
        "chat_id": chat_id,
        "text": message_text
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            print(f"Successfully sent Telegram message to {chat_id}. Response: {response.json()}")
            return response.json()
        except httpx.HTTPStatusError as e:
            print(f"Error sending Telegram message: {e.response.text}")
            raise e
        except Exception as e:
            print(f"An unexpected error occurred: {e}")
            raise e
