import httpx
import os
from typing import Dict, Any, List, Union

from app.models.integration import Integration
from app.services import integration_service

WHATSAPP_API_VERSION = "v19.0"

async def send_whatsapp_message(
    recipient_phone_number: str,
    message_text: str,
    integration: Integration
) -> Dict[str, Any]:
    """
    Sends a text message to a WhatsApp user via the Meta Cloud API.
    """
    credentials = integration_service.get_decrypted_credentials(integration)
    api_token = credentials.get("api_token") or credentials.get("access_token")
    phone_number_id = credentials.get("phone_number_id")

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

    async with httpx.AsyncClient() as client:
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
    integration: Integration
) -> Dict[str, Any]:
    """
    Sends an interactive message with buttons to a WhatsApp user.
    Supports both string options (legacy) and key-value dict options (new).
    """
    credentials = integration_service.get_decrypted_credentials(integration)
    api_token = credentials.get("api_token") or credentials.get("access_token")
    phone_number_id = credentials.get("phone_number_id")

    if not api_token or not phone_number_id:
        raise ValueError("WhatsApp credentials (api_token, phone_number_id) are not configured for this integration.")

    url = f"https://graph.facebook.com/{WHATSAPP_API_VERSION}/{phone_number_id}/messages"

    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
    }

    # WhatsApp allows up to 3 buttons, and each title has a 20-character limit.
    buttons = []
    for i, option in enumerate(options[:3]):
        if isinstance(option, dict):
            # New key-value format
            button_id = option.get("key", f"option_{i+1}")
            button_title = option.get("value", "")[:20]
        else:
            # Legacy string format
            button_id = f"option_{i+1}"
            button_title = str(option)[:20]

        buttons.append({
            "type": "reply",
            "reply": {
                "id": button_id,  # Use key as ID for proper response handling
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

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            print(f"Successfully sent interactive message to {recipient_phone_number}. Response: {response.json()}")
            return response.json()
        except httpx.HTTPStatusError as e:
            print(f"Error sending WhatsApp interactive message: {e.response.text}")
            raise e
        except Exception as e:
            print(f"An unexpected error occurred: {e}")
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

    async with httpx.AsyncClient() as client:
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

    async with httpx.AsyncClient() as client:
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
