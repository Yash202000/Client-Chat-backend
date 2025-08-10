from fastapi import APIRouter

from app.api.v1.endpoints import whatsapp, messenger, instagram, gmail, telegram

router = APIRouter()

router.include_router(whatsapp.router, prefix="/whatsapp", tags=["whatsapp-webhook"])
router.include_router(messenger.router, prefix="/messenger", tags=["messenger-webhook"])
router.include_router(instagram.router, prefix="/instagram", tags=["instagram-webhook"])
router.include_router(gmail.router, prefix="/gmail", tags=["gmail-webhook"])
router.include_router(telegram.router, prefix="/telegram", tags=["telegram-webhook"])
