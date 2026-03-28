"""
System Configuration Endpoint
Returns system-level configuration flags for the deployment.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, get_current_active_user
from app.models.user import User
from app.services.system_config_service import is_managed_mode
from app.core.config import settings

router = APIRouter()


@router.get("/config")
async def get_system_config(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Get system configuration flags.

    Returns deployment mode settings that control UI behavior:
    - managed_credentials: Whether credentials are managed at system level
    - credentials_editable: Whether users can edit credentials (inverse of managed)
    - deployment_mode: Overall deployment mode (cloud/on_premise)
    """
    managed_mode = is_managed_mode()

    return {
        "managed_credentials": managed_mode,
        "credentials_editable": not managed_mode,
        "deployment_mode": settings.DEPLOYMENT_MODE
    }
