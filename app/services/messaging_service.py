import httpx
import os
from typing import Dict, Any, List

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
    api_token = credentials.get("api_token")
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
    options: List[str],
    integration: Integration
) -> Dict[str, Any]:
    """
    Sends an interactive message with buttons to a WhatsApp user.
    """
    credentials = integration_service.get_decrypted_credentials(integration)
    api_token = credentials.get("api_token")
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
        buttons.append({
            "type": "reply",
            "reply": {
                "id": f"option_{i+1}",
                "title": option[:20]  # Truncate title to 20 chars
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

async def send_messenger_message(
    recipient_psid: str,
    message_text: str,
    integration: Integration
) -> Dict[str, Any]:
    """
    Sends a text message to a Messenger user via the Meta Graph API.
    """
    credentials = integration_service.get_decrypted_credentials(integration)
    page_access_token = credentials.get("page_access_token")

    if not page_access_token:
        raise ValueError("Messenger credentials (page_access_token) are not configured for this integration.")

    url = f"https://graph.facebook.com/{WHATSAPP_API_VERSION}/me/messages"
    
    headers = {
        "Authorization": f"Bearer {page_access_token}",
        "Content-Type": "application/json",
    }
    
    payload = {
        "recipient": {"id": recipient_psid},
        "message": {"text": message_text},
        "messaging_type": "RESPONSE"
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            print(f"Successfully sent Messenger message to {recipient_psid}. Response: {response.json()}")
            return response.json()
        except httpx.HTTPStatusError as e:
            print(f"Error sending Messenger message: {e.response.text}")
            raise e
        except Exception as e:
            print(f"An unexpected error occurred: {e}")
            raise e
