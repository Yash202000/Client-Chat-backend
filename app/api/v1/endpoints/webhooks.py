from fastapi import APIRouter

from app.api.v1.endpoints import whatsapp, messenger

router = APIRouter()

router.include_router(whatsapp.router, prefix="/whatsapp", tags=["whatsapp-webhook"])
router.include_router(messenger.router, prefix="/messenger", tags=["messenger-webhook"])