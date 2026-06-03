"""
Cash on Delivery (COD) Verification endpoints

POST /cod/verify          — send COD confirmation to customer
GET  /cod/{id}            — get verification status
GET  /cod/order/{order_id} — list all verifications for an order
"""
import logging
from decimal import Decimal
from typing import Optional, List, Literal
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, get_current_active_user
from app.models.user import User
from app.services import cod_service

router = APIRouter()
logger = logging.getLogger(__name__)


class CODVerifyRequest(BaseModel):
    order_id: str
    channel: Literal["whatsapp", "sms"]
    recipient: str                      # customer phone in E.164 format
    order_amount: Optional[Decimal] = None
    currency: str = "INR"
    customer_name: Optional[str] = None
    webhook_url: Optional[str] = None   # fires on YES/NO reply
    metadata: Optional[dict] = None


class CODVerifyResponse(BaseModel):
    verification_id: str
    order_id: str
    channel: str
    recipient: str
    status: str
    expires_at: datetime
    message: str = "COD confirmation sent to customer"


class CODStatusResponse(BaseModel):
    verification_id: str
    order_id: str
    channel: str
    recipient: str
    status: str
    customer_reply: Optional[str]
    order_amount: Optional[Decimal]
    currency: str
    expires_at: datetime
    replied_at: Optional[datetime]
    created_at: datetime


@router.post("/verify", response_model=CODVerifyResponse)
async def send_cod_verification(
    request: CODVerifyRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
    x_company_id: int = Header(...),
):
    """Send a COD confirmation message to the customer via WhatsApp or SMS."""
    try:
        cod = await cod_service.create_cod_verification(
            db=db,
            company_id=x_company_id,
            order_id=request.order_id,
            channel=request.channel,
            recipient=request.recipient,
            order_amount=request.order_amount,
            currency=request.currency,
            customer_name=request.customer_name,
            webhook_url=request.webhook_url,
            metadata=request.metadata,
        )
        return CODVerifyResponse(
            verification_id=cod.verification_id,
            order_id=cod.order_id,
            channel=cod.channel.value,
            recipient=cod.recipient,
            status=cod.status.value,
            expires_at=cod.expires_at,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"[COD] Error: {e}")
        raise HTTPException(status_code=500, detail="Failed to send COD verification.")


@router.get("/{verification_id}", response_model=CODStatusResponse)
def get_cod_status(
    verification_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
    x_company_id: int = Header(...),
):
    cod = cod_service.get_cod_status(db, verification_id, x_company_id)
    if not cod:
        raise HTTPException(status_code=404, detail="COD verification not found.")
    return CODStatusResponse(
        verification_id=cod.verification_id,
        order_id=cod.order_id,
        channel=cod.channel.value,
        recipient=cod.recipient,
        status=cod.status.value,
        customer_reply=cod.customer_reply,
        order_amount=cod.order_amount,
        currency=cod.currency,
        expires_at=cod.expires_at,
        replied_at=cod.replied_at,
        created_at=cod.created_at,
    )


@router.get("/order/{order_id}", response_model=List[CODStatusResponse])
def list_by_order(
    order_id: str,
    status: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
    x_company_id: int = Header(...),
):
    """List all COD verifications for a specific order ID."""
    results = cod_service.list_cod_verifications(
        db=db,
        company_id=x_company_id,
        order_id=order_id,
        status=status,
    )
    return [
        CODStatusResponse(
            verification_id=c.verification_id,
            order_id=c.order_id,
            channel=c.channel.value,
            recipient=c.recipient,
            status=c.status.value,
            customer_reply=c.customer_reply,
            order_amount=c.order_amount,
            currency=c.currency,
            expires_at=c.expires_at,
            replied_at=c.replied_at,
            created_at=c.created_at,
        )
        for c in results
    ]
