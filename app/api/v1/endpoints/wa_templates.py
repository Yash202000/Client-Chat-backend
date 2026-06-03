"""
WhatsApp Template endpoints

GET  /wa-templates           — list templates synced from Meta
POST /wa-templates/send      — send a template to a recipient
"""
import logging
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, get_current_active_user
from app.models.user import User
from app.services import wa_template_service

router = APIRouter()
logger = logging.getLogger(__name__)


class TemplateSendRequest(BaseModel):
    recipient_phone: str
    template_name: str
    language_code: str = "en_US"
    variables: Optional[List[str]] = None   # simple list → body params


class TemplateSendResponse(BaseModel):
    success: bool
    message_id: Optional[str] = None


@router.get("")
async def list_templates(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
    x_company_id: int = Header(...),
):
    """Fetch templates from Meta and return formatted list."""
    try:
        raw = await wa_template_service.fetch_templates_from_meta(db, x_company_id)
        return [wa_template_service.format_template_for_ui(t) for t in raw]
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"[WA Templates] fetch error: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch templates from Meta.")


@router.post("/send", response_model=TemplateSendResponse)
async def send_template(
    body: TemplateSendRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
    x_company_id: int = Header(...),
):
    """Send a Meta-approved template message."""
    # Build components from simple variables list
    components = None
    if body.variables:
        components = [{
            "type": "body",
            "parameters": [{"type": "text", "text": v} for v in body.variables],
        }]

    try:
        result = await wa_template_service.send_template_message(
            db=db,
            company_id=x_company_id,
            recipient_phone=body.recipient_phone,
            template_name=body.template_name,
            language_code=body.language_code,
            components=components,
        )
        msg_id = result.get("messages", [{}])[0].get("id")
        return TemplateSendResponse(success=True, message_id=msg_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"[WA Templates] send error: {e}")
        raise HTTPException(status_code=500, detail="Failed to send template.")
