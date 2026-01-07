"""
Token Usage API Endpoints

Provides endpoints for viewing and managing LLM token usage and costs.
"""
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from typing import Optional, List
from datetime import datetime, timedelta

from app.core.dependencies import get_db, get_current_user
from app.services import token_usage_service, company_settings_service
from app.models.user import User
from app.schemas.token_usage import (
    TokenUsageResponse,
    TokenUsageStats,
    DailyUsage,
    UsageAlertResponse,
    TokenTrackingSettings,
    TokenTrackingSettingsUpdate
)

router = APIRouter()


@router.get("/", response_model=List[TokenUsageResponse])
async def get_token_usage(
    agent_id: Optional[int] = Query(None, description="Filter by agent ID"),
    provider: Optional[str] = Query(None, description="Filter by provider (openai, groq, gemini)"),
    start_date: Optional[datetime] = Query(None, description="Start date filter"),
    end_date: Optional[datetime] = Query(None, description="End date filter"),
    limit: int = Query(100, ge=1, le=500, description="Maximum records to return"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get token usage records for the current user's company.

    Returns paginated list of token usage records with optional filters.
    """
    records = token_usage_service.get_usage_records(
        db=db,
        company_id=current_user.company_id,
        agent_id=agent_id,
        provider=provider,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        offset=offset
    )

    return records


@router.get("/stats", response_model=TokenUsageStats)
async def get_token_usage_stats(
    start_date: Optional[datetime] = Query(None, description="Start date (defaults to start of month)"),
    end_date: Optional[datetime] = Query(None, description="End date (defaults to now)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get aggregated token usage statistics.

    Returns comprehensive statistics including:
    - Total tokens and estimated cost
    - Breakdown by provider, agent, and model
    """
    stats = token_usage_service.get_usage_stats(
        db=db,
        company_id=current_user.company_id,
        start_date=start_date,
        end_date=end_date
    )

    return TokenUsageStats(**stats)


@router.get("/daily", response_model=List[DailyUsage])
async def get_daily_usage(
    days: int = Query(30, ge=1, le=90, description="Number of days to include"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get daily token usage breakdown for charting.

    Returns daily totals for the specified number of days.
    """
    daily = token_usage_service.get_daily_usage(
        db=db,
        company_id=current_user.company_id,
        days=days
    )

    return [DailyUsage(**d) for d in daily]


@router.get("/by-session/{session_id}")
async def get_session_usage(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get token usage for a specific session.

    Returns all token usage records for the specified conversation session.
    """
    records = token_usage_service.get_usage_by_session(
        db=db,
        session_id=session_id,
        company_id=current_user.company_id
    )

    return records


@router.get("/by-agent/{agent_id}")
async def get_agent_usage(
    agent_id: int,
    start_date: Optional[datetime] = Query(None, description="Start date filter"),
    end_date: Optional[datetime] = Query(None, description="End date filter"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get aggregated token usage for a specific agent.

    Returns total tokens, cost, and request count for the agent.
    """
    usage = token_usage_service.get_usage_by_agent(
        db=db,
        agent_id=agent_id,
        company_id=current_user.company_id,
        start_date=start_date,
        end_date=end_date
    )

    return usage


@router.get("/settings", response_model=TokenTrackingSettings)
async def get_tracking_settings(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get token tracking settings for the company.

    Returns current tracking mode, budget limits, and alert configuration.
    """
    settings = company_settings_service.get_or_create_settings(db, current_user.company_id)

    return TokenTrackingSettings(
        token_tracking_mode=settings.token_tracking_mode or "detailed",
        monthly_budget_cents=settings.monthly_budget_cents,
        alert_threshold_percent=settings.alert_threshold_percent or 80,
        alert_email=settings.alert_email,
        alerts_enabled=settings.alerts_enabled if settings.alerts_enabled is not None else True,
        per_agent_daily_limit_cents=settings.per_agent_daily_limit_cents
    )


@router.put("/settings", response_model=TokenTrackingSettings)
async def update_tracking_settings(
    settings_update: TokenTrackingSettingsUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Update token tracking settings for the company.

    Allows configuration of:
    - Tracking mode (none, aggregated, detailed)
    - Monthly budget and alert thresholds
    - Alert email notifications
    """
    settings = company_settings_service.get_or_create_settings(db, current_user.company_id)

    # Update only provided fields
    if settings_update.token_tracking_mode is not None:
        settings.token_tracking_mode = settings_update.token_tracking_mode
    if settings_update.monthly_budget_cents is not None:
        settings.monthly_budget_cents = settings_update.monthly_budget_cents
    if settings_update.alert_threshold_percent is not None:
        settings.alert_threshold_percent = settings_update.alert_threshold_percent
    if settings_update.alert_email is not None:
        settings.alert_email = settings_update.alert_email
    if settings_update.alerts_enabled is not None:
        settings.alerts_enabled = settings_update.alerts_enabled
    if settings_update.per_agent_daily_limit_cents is not None:
        settings.per_agent_daily_limit_cents = settings_update.per_agent_daily_limit_cents

    db.commit()
    db.refresh(settings)

    return TokenTrackingSettings(
        token_tracking_mode=settings.token_tracking_mode or "detailed",
        monthly_budget_cents=settings.monthly_budget_cents,
        alert_threshold_percent=settings.alert_threshold_percent or 80,
        alert_email=settings.alert_email,
        alerts_enabled=settings.alerts_enabled if settings.alerts_enabled is not None else True,
        per_agent_daily_limit_cents=settings.per_agent_daily_limit_cents
    )


@router.get("/alerts", response_model=List[UsageAlertResponse])
async def get_usage_alerts(
    include_acknowledged: bool = Query(False, description="Include acknowledged alerts"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get usage alerts for the company.

    Returns budget warnings and exceeded alerts.
    """
    alerts = token_usage_service.get_active_alerts(
        db=db,
        company_id=current_user.company_id,
        include_acknowledged=include_acknowledged
    )

    return alerts


@router.post("/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(
    alert_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Acknowledge a usage alert.

    Marks the alert as acknowledged by the current user.
    """
    from app.models.usage_alert import UsageAlert

    # Verify alert belongs to user's company
    alert = db.query(UsageAlert).filter(
        UsageAlert.id == alert_id,
        UsageAlert.company_id == current_user.company_id
    ).first()

    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    updated_alert = token_usage_service.acknowledge_alert(
        db=db,
        alert_id=alert_id,
        user_id=current_user.id
    )

    return {"message": "Alert acknowledged", "alert_id": alert_id}


@router.get("/monthly-spend")
async def get_monthly_spend(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get current month's spending.

    Returns total spend in cents and USD for the current billing month.
    """
    spend_cents = token_usage_service.get_monthly_spend(db, current_user.company_id)
    budget_settings = company_settings_service.get_budget_settings(db, current_user.company_id)

    return {
        "spend_cents": spend_cents,
        "spend_usd": spend_cents / 100,
        "budget_cents": budget_settings.get("monthly_budget_cents"),
        "budget_usd": budget_settings.get("monthly_budget_cents", 0) / 100 if budget_settings.get("monthly_budget_cents") else None,
        "percent_used": round(spend_cents / budget_settings.get("monthly_budget_cents") * 100, 2) if budget_settings.get("monthly_budget_cents") else None
    }
