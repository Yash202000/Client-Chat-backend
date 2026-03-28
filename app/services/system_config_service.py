"""
System Configuration Service
Handles deployment mode configuration and system-level credential management.
"""
from typing import Optional
import logging

from app.core.config import settings

logger = logging.getLogger(__name__)


def is_managed_mode() -> bool:
    """
    Check if credentials are managed at system level (Cloud/SaaS deployment).

    Returns:
        bool: True if in managed mode (system-level credentials), False if self-hosted (user vault)
    """
    return settings.MANAGED_CREDENTIALS


def get_system_credential(service: str) -> Optional[str]:
    """
    Get system-level credential for a service when in managed mode.

    Args:
        service: Service name (e.g., "anthropic", "openai", "groq", "gemini")

    Returns:
        Optional[str]: API key if available and in managed mode, None otherwise
    """
    if not is_managed_mode():
        logger.debug(f"Not in managed mode, skipping system credential lookup for {service}")
        return None

    service_lower = service.lower()

    # Map service names to configuration keys
    service_map = {
        "anthropic": settings.ANTHROPIC_API_KEY,
        "openai": settings.OPENAI_API_KEY,
        "groq": settings.GROQ_API_KEY,
        "gemini": settings.GEMINI_API_KEY or settings.GOOGLE_API_KEY,  # Support both names
        "google": settings.GOOGLE_API_KEY,
    }

    credential = service_map.get(service_lower)

    if credential:
        logger.info(f"Using system-level credential for {service}")
    else:
        logger.warning(f"Managed mode enabled but no system credential configured for {service}")

    return credential if credential else None
