from sqlalchemy.orm import Session
from app.models.published_widget_settings import PublishedWidgetSettings
from app.schemas.published_widget_settings import PublishedWidgetSettingsCreate, PublishedWidgetSettingsUpdate
from datetime import datetime
import json
from typing import Optional


def get_published_widget_settings(db: Session, publish_id: str) -> Optional[PublishedWidgetSettings]:
    """Get published settings by publish_id"""
    return db.query(PublishedWidgetSettings).filter(
        PublishedWidgetSettings.publish_id == publish_id
    ).first()


def get_by_agent_id(db: Session, agent_id: int) -> Optional[PublishedWidgetSettings]:
    """Get published settings by agent_id"""
    return db.query(PublishedWidgetSettings).filter(
        PublishedWidgetSettings.agent_id == agent_id
    ).first()


def create_or_update(db: Session, agent_id: int, settings: dict) -> tuple[PublishedWidgetSettings, bool]:
    """
    Create or update published settings for an agent.
    Returns (settings, is_new) tuple.
    """
    existing = get_by_agent_id(db, agent_id)

    if existing:
        # Update existing - keep same publish_id
        existing.settings = json.dumps(settings)
        existing.is_active = True  # Re-activate if it was unpublished
        existing.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(existing)
        return existing, False
    else:
        # Create new
        db_settings = PublishedWidgetSettings(
            agent_id=agent_id,
            settings=json.dumps(settings),
            is_active=True
        )
        db.add(db_settings)
        db.commit()
        db.refresh(db_settings)
        return db_settings, True


def set_active_status(db: Session, agent_id: int, is_active: bool) -> Optional[PublishedWidgetSettings]:
    """Set the is_active status for an agent's published settings"""
    existing = get_by_agent_id(db, agent_id)

    if existing:
        existing.is_active = is_active
        existing.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(existing)
        return existing

    return None


# Keep old function for backward compatibility (deprecated)
def create_published_widget_settings(db: Session, settings: dict) -> PublishedWidgetSettings:
    """
    DEPRECATED: Use create_or_update instead.
    Creates a new published widget settings without agent_id link.
    """
    db_settings = PublishedWidgetSettings(settings=json.dumps(settings))
    db.add(db_settings)
    db.commit()
    db.refresh(db_settings)
    return db_settings
