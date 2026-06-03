"""
WhatsApp Catalog endpoints

GET  /catalog/products               — list products from Meta Commerce Catalog
POST /catalog/message/single         — send single-product interactive message
POST /catalog/message/multi          — send multi-product (MPM) interactive message
"""
import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, get_current_active_user
from app.models.user import User
from app.services import catalog_service

router = APIRouter()
logger = logging.getLogger(__name__)


class SingleProductRequest(BaseModel):
    recipient_phone: str
    product_retailer_id: str
    body_text: str = "Check out this product!"
    footer_text: Optional[str] = None


class MPMSection(BaseModel):
    title: str
    product_retailer_ids: List[str]


class MultiProductRequest(BaseModel):
    recipient_phone: str
    sections: List[MPMSection]
    header_text: str = "Our Products"
    body_text: str = "Browse our catalog"
    footer_text: Optional[str] = None


@router.get("/products")
async def list_products(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
    x_company_id: int = Header(...),
    limit: int = 50,
):
    """Fetch products from the Meta Commerce Catalog."""
    try:
        products = await catalog_service.fetch_products(db, x_company_id, limit=limit)
        return {"products": products, "total": len(products)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"[Catalog] fetch products error: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch products from Meta.")


@router.post("/message/single")
async def send_single_product(
    body: SingleProductRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
    x_company_id: int = Header(...),
):
    """Send a single-product WhatsApp interactive message."""
    try:
        result = await catalog_service.send_single_product(
            db=db,
            company_id=x_company_id,
            recipient_phone=body.recipient_phone,
            product_retailer_id=body.product_retailer_id,
            body_text=body.body_text,
            footer_text=body.footer_text,
        )
        msg_id = result.get("messages", [{}])[0].get("id")
        return {"success": True, "message_id": msg_id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"[Catalog] single product send error: {e}")
        raise HTTPException(status_code=500, detail="Failed to send catalog message.")


@router.post("/message/multi")
async def send_multi_product(
    body: MultiProductRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
    x_company_id: int = Header(...),
):
    """Send a multi-product (MPM) WhatsApp interactive message."""
    if not body.sections:
        raise HTTPException(status_code=400, detail="At least one section required.")
    total_products = sum(len(s.product_retailer_ids) for s in body.sections)
    if total_products > 30:
        raise HTTPException(status_code=400, detail="MPM supports a maximum of 30 products across all sections.")

    try:
        result = await catalog_service.send_multi_product(
            db=db,
            company_id=x_company_id,
            recipient_phone=body.recipient_phone,
            sections=[s.dict() for s in body.sections],
            header_text=body.header_text,
            body_text=body.body_text,
            footer_text=body.footer_text,
        )
        msg_id = result.get("messages", [{}])[0].get("id")
        return {"success": True, "message_id": msg_id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"[Catalog] multi product send error: {e}")
        raise HTTPException(status_code=500, detail="Failed to send catalog message.")
