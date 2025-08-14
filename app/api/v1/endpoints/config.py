from fastapi import APIRouter
from app.core.config import settings

router = APIRouter()

@router.get("/linkedin-client-id")
def get_linkedin_client_id():
    """
    Provides the LinkedIn Client ID to the frontend.
    """
    return {"client_id": settings.LINKEDIN_CLIENT_ID}

@router.get("/google-client-id")
def get_google_client_id():
    """
    Provides the Google Client ID to the frontend.
    """
    return {"client_id": settings.GMAIL_CLIENT_ID}
