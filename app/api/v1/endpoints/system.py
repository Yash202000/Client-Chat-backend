"""
System Configuration Endpoint
Returns system-level configuration flags for the deployment.
"""
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, get_current_active_user
from app.models.user import User
from app.services.system_config_service import is_managed_mode
from app.core.config import settings

router = APIRouter()
logger = logging.getLogger(__name__)


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


# ---------------------------------------------------------------------------
# Public health endpoint — always reachable, even during maintenance mode
# ---------------------------------------------------------------------------

@router.get("/health")
async def health_check():
    """Public health check. Returns 200 even during maintenance mode."""
    return {
        "status": "ok",
        "maintenance_mode": settings.MAINTENANCE_MODE,
        "signup_paused": settings.SIGNUP_PAUSED,
        "timestamp": datetime.utcnow().isoformat(),
    }


# ---------------------------------------------------------------------------
# Kill-switch / rollback toggle endpoints (super-admin only)
# ---------------------------------------------------------------------------

@router.post("/maintenance/enable")
async def enable_maintenance(current_user: User = Depends(get_current_active_user)):
    """Enable maintenance mode — returns 503 for all non-exempt paths."""
    if not current_user.is_super_admin:
        raise HTTPException(status_code=403, detail="Super admin only")
    settings.MAINTENANCE_MODE = True
    logger.warning("[KILLSWITCH] Maintenance mode ENABLED by user %s", current_user.id)
    return {"status": "maintenance_mode_enabled"}


@router.post("/maintenance/disable")
async def disable_maintenance(current_user: User = Depends(get_current_active_user)):
    """Disable maintenance mode — resumes normal traffic."""
    if not current_user.is_super_admin:
        raise HTTPException(status_code=403, detail="Super admin only")
    settings.MAINTENANCE_MODE = False
    logger.warning("[KILLSWITCH] Maintenance mode DISABLED by user %s", current_user.id)
    return {"status": "maintenance_mode_disabled"}


@router.post("/signups/pause")
async def pause_signups(current_user: User = Depends(get_current_active_user)):
    """Pause new user registrations."""
    if not current_user.is_super_admin:
        raise HTTPException(status_code=403, detail="Super admin only")
    settings.SIGNUP_PAUSED = True
    logger.warning("[KILLSWITCH] Signups PAUSED by user %s", current_user.id)
    return {"status": "signups_paused"}


@router.post("/signups/resume")
async def resume_signups(current_user: User = Depends(get_current_active_user)):
    """Resume new user registrations."""
    if not current_user.is_super_admin:
        raise HTTPException(status_code=403, detail="Super admin only")
    settings.SIGNUP_PAUSED = False
    logger.warning("[KILLSWITCH] Signups RESUMED by user %s", current_user.id)
    return {"status": "signups_resumed"}

