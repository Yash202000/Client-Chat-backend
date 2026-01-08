
from sqlalchemy.orm import Session
from app.models import company_settings as models_company_settings
from app.schemas import company_settings as schemas_company_settings

def get_company_settings(db: Session, company_id: int):
    return db.query(models_company_settings.CompanySettings).filter(models_company_settings.CompanySettings.company_id == company_id).first()

def create_company_settings(db: Session, company_id: int, settings: schemas_company_settings.CompanySettingsCreate):
    db_settings = models_company_settings.CompanySettings(**settings.model_dump(), company_id=company_id)
    db.add(db_settings)
    db.commit()
    db.refresh(db_settings)
    return db_settings

def update_company_settings(db: Session, company_id: int, settings: schemas_company_settings.CompanySettingsUpdate):
    db_settings = get_company_settings(db, company_id)
    if db_settings:
        # Use exclude_unset=True to only update fields that were explicitly set
        for key, value in settings.model_dump(exclude_unset=True).items():
            setattr(db_settings, key, value)
        db.commit()
        db.refresh(db_settings)
    return db_settings


def get_or_create_settings(db: Session, company_id: int) -> models_company_settings.CompanySettings:
    """
    Get company settings, creating default settings if they don't exist.

    Args:
        db: Database session
        company_id: Company ID

    Returns:
        CompanySettings record
    """
    settings = get_company_settings(db, company_id)
    if not settings:
        settings = models_company_settings.CompanySettings(company_id=company_id)
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings


def get_token_tracking_mode(db: Session, company_id: int) -> str:
    """
    Get the token tracking mode for a company.

    Args:
        db: Database session
        company_id: Company ID

    Returns:
        Tracking mode: "none", "aggregated", or "detailed"
    """
    settings = get_or_create_settings(db, company_id)
    return settings.token_tracking_mode or "detailed"


def should_track_tokens(db: Session, company_id: int) -> bool:
    """
    Check if token tracking is enabled for a company.

    Args:
        db: Database session
        company_id: Company ID

    Returns:
        True if tracking is enabled (mode is not "none")
    """
    mode = get_token_tracking_mode(db, company_id)
    return mode != "none"


def get_budget_settings(db: Session, company_id: int) -> dict:
    """
    Get budget and alert settings for a company.

    Args:
        db: Database session
        company_id: Company ID

    Returns:
        Dictionary with budget settings
    """
    settings = get_or_create_settings(db, company_id)
    return {
        "monthly_budget_cents": settings.monthly_budget_cents,
        "alert_threshold_percent": settings.alert_threshold_percent or 80,
        "alert_email": settings.alert_email,
        "alerts_enabled": settings.alerts_enabled if settings.alerts_enabled is not None else True,
        "per_agent_daily_limit_cents": settings.per_agent_daily_limit_cents
    }
