"""
WhatsApp Business Template Service

Handles Meta-approved message templates:
  - Fetch templates from Meta API (synced from WABA)
  - Send template messages to contacts
  - Cache template list per integration

Templates are required for business-initiated messages sent outside the
24-hour customer service window.
"""
import logging
from typing import Optional, List, Dict, Any

import httpx
from sqlalchemy.orm import Session

from app.services import integration_service
from app.services.whatsapp_token_service import whatsapp_token_service

logger = logging.getLogger(__name__)
WHATSAPP_API_VERSION = "v19.0"


async def fetch_templates_from_meta(db: Session, company_id: int) -> List[Dict]:
    """
    Fetch all approved/pending templates from Meta WABA.
    Returns raw Meta API response list.
    """
    integration = integration_service.get_integration_by_type_and_company(db, "whatsapp", company_id)
    if not integration:
        raise ValueError("WhatsApp integration not configured.")

    creds = integration_service.get_decrypted_credentials(integration)
    waba_id = creds.get("waba_id") or creds.get("business_account_id")
    api_token = await whatsapp_token_service.ensure_valid_token(db, integration)

    if not waba_id:
        raise ValueError("WhatsApp Business Account ID (waba_id) not configured in integration credentials.")

    url = f"https://graph.facebook.com/{WHATSAPP_API_VERSION}/{waba_id}/message_templates"
    params = {"limit": 100, "fields": "name,status,language,category,components"}

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url, headers={"Authorization": f"Bearer {api_token}"}, params=params)

    if resp.status_code != 200:
        raise ValueError(f"Meta API error: {resp.text}")

    data = resp.json()
    return data.get("data", [])


async def send_template_message(
    db: Session,
    company_id: int,
    recipient_phone: str,
    template_name: str,
    language_code: str,
    components: Optional[List[Dict]] = None,
) -> Dict[str, Any]:
    """
    Send a Meta-approved template message to a recipient.

    components example (body variables):
    [{"type": "body", "parameters": [{"type": "text", "text": "John"}]}]
    """
    integration = integration_service.get_integration_by_type_and_company(db, "whatsapp", company_id)
    if not integration:
        raise ValueError("WhatsApp integration not configured.")

    creds = integration_service.get_decrypted_credentials(integration)
    phone_number_id = creds.get("phone_number_id")
    api_token = await whatsapp_token_service.ensure_valid_token(db, integration)

    if not api_token or not phone_number_id:
        raise ValueError("WhatsApp credentials not configured.")

    payload: Dict[str, Any] = {
        "messaging_product": "whatsapp",
        "to": recipient_phone,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": language_code},
        },
    }
    if components:
        payload["template"]["components"] = components

    url = f"https://graph.facebook.com/{WHATSAPP_API_VERSION}/{phone_number_id}/messages"

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            url,
            headers={"Authorization": f"Bearer {api_token}", "Content-Type": "application/json"},
            json=payload,
        )

    if resp.status_code not in (200, 201):
        raise ValueError(f"Meta API error: {resp.text}")

    logger.info(f"[WA Template] Sent '{template_name}' to {recipient_phone}")
    return resp.json()


def _extract_body_text(components: List[Dict]) -> str:
    """Pull body text from template components for display."""
    for c in components:
        if c.get("type") == "BODY":
            return c.get("text", "")
    return ""


def _extract_header(components: List[Dict]) -> Optional[str]:
    for c in components:
        if c.get("type") == "HEADER":
            return c.get("text") or c.get("format", "")
    return None


def _extract_buttons(components: List[Dict]) -> List[str]:
    for c in components:
        if c.get("type") == "BUTTONS":
            return [b.get("text", "") for b in c.get("buttons", [])]
    return []


def format_template_for_ui(raw: Dict) -> Dict:
    """Normalize Meta API template response into a clean UI-friendly shape."""
    components = raw.get("components", [])
    return {
        "name": raw.get("name"),
        "status": raw.get("status"),          # APPROVED / PENDING / REJECTED
        "language": raw.get("language"),
        "category": raw.get("category"),
        "header": _extract_header(components),
        "body": _extract_body_text(components),
        "buttons": _extract_buttons(components),
        "components": components,              # full raw for sending
    }
