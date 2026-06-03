"""
WhatsApp Catalog / Commerce Service

Handles:
  - Fetching products from Meta Commerce Catalog API
  - Sending single-product and multi-product (MPM) interactive messages

Requires `catalog_id` in the WhatsApp integration credentials.
"""
import logging
from typing import Optional, List, Dict, Any

import httpx
from sqlalchemy.orm import Session

from app.services import integration_service
from app.services.whatsapp_token_service import whatsapp_token_service

logger = logging.getLogger(__name__)
WHATSAPP_API_VERSION = "v19.0"
PRODUCT_FIELDS = "id,retailer_id,name,description,price,sale_price,currency,image_url,availability,category,url"


async def fetch_products(db: Session, company_id: int, limit: int = 50) -> List[Dict]:
    """Fetch products from the Meta Commerce Catalog linked to the WA integration."""
    integration = integration_service.get_integration_by_type_and_company(db, "whatsapp", company_id)
    if not integration:
        raise ValueError("WhatsApp integration not configured.")

    creds = integration_service.get_decrypted_credentials(integration)
    catalog_id = creds.get("catalog_id") or creds.get("commerce_catalog_id")
    if not catalog_id:
        raise ValueError("catalog_id not set in WhatsApp integration credentials.")

    api_token = await whatsapp_token_service.ensure_valid_token(db, integration)

    url = f"https://graph.facebook.com/{WHATSAPP_API_VERSION}/{catalog_id}/products"
    params = {"fields": PRODUCT_FIELDS, "limit": limit}

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url, headers={"Authorization": f"Bearer {api_token}"}, params=params)

    if resp.status_code != 200:
        raise ValueError(f"Meta Catalog API error: {resp.text}")

    return resp.json().get("data", [])


async def send_single_product(
    db: Session,
    company_id: int,
    recipient_phone: str,
    product_retailer_id: str,
    body_text: str = "Check out this product!",
    footer_text: Optional[str] = None,
) -> Dict[str, Any]:
    """Send a single-product WhatsApp interactive message."""
    integration = integration_service.get_integration_by_type_and_company(db, "whatsapp", company_id)
    if not integration:
        raise ValueError("WhatsApp integration not configured.")

    creds = integration_service.get_decrypted_credentials(integration)
    catalog_id = creds.get("catalog_id") or creds.get("commerce_catalog_id")
    phone_number_id = creds.get("phone_number_id")
    api_token = await whatsapp_token_service.ensure_valid_token(db, integration)

    if not catalog_id:
        raise ValueError("catalog_id not set in WhatsApp integration credentials.")

    interactive: Dict[str, Any] = {
        "type": "product",
        "body": {"text": body_text},
        "action": {
            "catalog_id": catalog_id,
            "product_retailer_id": product_retailer_id,
        },
    }
    if footer_text:
        interactive["footer"] = {"text": footer_text}

    return await _send_interactive(phone_number_id, api_token, recipient_phone, interactive)


async def send_multi_product(
    db: Session,
    company_id: int,
    recipient_phone: str,
    sections: List[Dict],   # [{"title": str, "product_retailer_ids": [str]}]
    header_text: str = "Our Products",
    body_text: str = "Browse our catalog",
    footer_text: Optional[str] = None,
) -> Dict[str, Any]:
    """Send a multi-product list (MPM) interactive message."""
    integration = integration_service.get_integration_by_type_and_company(db, "whatsapp", company_id)
    if not integration:
        raise ValueError("WhatsApp integration not configured.")

    creds = integration_service.get_decrypted_credentials(integration)
    catalog_id = creds.get("catalog_id") or creds.get("commerce_catalog_id")
    phone_number_id = creds.get("phone_number_id")
    api_token = await whatsapp_token_service.ensure_valid_token(db, integration)

    if not catalog_id:
        raise ValueError("catalog_id not set in WhatsApp integration credentials.")

    mpm_sections = [
        {
            "title": s.get("title", ""),
            "product_items": [{"product_retailer_id": pid} for pid in s.get("product_retailer_ids", [])],
        }
        for s in sections
    ]

    interactive: Dict[str, Any] = {
        "type": "product_list",
        "header": {"type": "text", "text": header_text},
        "body": {"text": body_text},
        "action": {
            "catalog_id": catalog_id,
            "sections": mpm_sections,
        },
    }
    if footer_text:
        interactive["footer"] = {"text": footer_text}

    return await _send_interactive(phone_number_id, api_token, recipient_phone, interactive)


async def _send_interactive(
    phone_number_id: str,
    api_token: str,
    to: str,
    interactive: Dict,
) -> Dict[str, Any]:
    url = f"https://graph.facebook.com/{WHATSAPP_API_VERSION}/{phone_number_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": interactive,
    }
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            url,
            headers={"Authorization": f"Bearer {api_token}", "Content-Type": "application/json"},
            json=payload,
        )
    if resp.status_code not in (200, 201):
        raise ValueError(f"Meta API error: {resp.text}")
    return resp.json()
