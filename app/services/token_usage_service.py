"""
Token Usage Service

Service for logging and querying LLM token usage for cost tracking and budget management.
"""
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, extract

from app.models.token_usage import TokenUsage
from app.models.usage_alert import UsageAlert
from app.models.agent import Agent
from app.services import company_settings_service

logger = logging.getLogger(__name__)


# Cost pricing table (USD per 1M tokens)
# Prices are approximate and should be updated periodically
PRICING_TABLE = {
    "openai": {
        "gpt-4o": {"input": 2.50, "output": 10.00},
        "gpt-4o-mini": {"input": 0.15, "output": 0.60},
        "gpt-4-turbo": {"input": 10.00, "output": 30.00},
        "gpt-4": {"input": 30.00, "output": 60.00},
        "gpt-3.5-turbo": {"input": 0.50, "output": 1.50},
        "default": {"input": 2.50, "output": 10.00}
    },
    "groq": {
        "llama-3.1-8b-instant": {"input": 0.05, "output": 0.08},
        "llama-3.1-70b-versatile": {"input": 0.59, "output": 0.79},
        "llama-3.2-90b-vision-preview": {"input": 0.90, "output": 0.90},
        "mixtral-8x7b-32768": {"input": 0.24, "output": 0.24},
        "gemma2-9b-it": {"input": 0.20, "output": 0.20},
        "default": {"input": 0.10, "output": 0.15}
    },
    "gemini": {
        "gemini-1.5-flash": {"input": 0.075, "output": 0.30},
        "gemini-1.5-pro": {"input": 1.25, "output": 5.00},
        "gemini-2.0-flash-exp": {"input": 0.10, "output": 0.40},
        "default": {"input": 0.10, "output": 0.40}
    }
}


def calculate_cost_cents(
    provider: str,
    model_name: str,
    prompt_tokens: int,
    completion_tokens: int
) -> int:
    """
    Calculate estimated cost in cents based on provider pricing.

    Args:
        provider: LLM provider (openai, groq, gemini)
        model_name: Model name
        prompt_tokens: Number of input tokens
        completion_tokens: Number of output tokens

    Returns:
        Estimated cost in USD cents
    """
    provider_pricing = PRICING_TABLE.get(provider.lower(), PRICING_TABLE["openai"])
    model_pricing = provider_pricing.get(model_name, provider_pricing.get("default", {"input": 1.0, "output": 2.0}))

    # Calculate cost (prices are per 1M tokens, convert to cents)
    input_cost = (prompt_tokens / 1_000_000) * model_pricing["input"] * 100
    output_cost = (completion_tokens / 1_000_000) * model_pricing["output"] * 100

    return int(input_cost + output_cost)


def log_token_usage(
    db: Session,
    company_id: int,
    provider: str,
    model_name: str,
    prompt_tokens: int,
    completion_tokens: int,
    agent_id: Optional[int] = None,
    session_id: Optional[str] = None,
    request_type: Optional[str] = None
) -> Optional[TokenUsage]:
    """
    Log token usage for an LLM API call.

    Respects company settings for tracking mode.

    Args:
        db: Database session
        company_id: Company ID
        provider: LLM provider
        model_name: Model name
        prompt_tokens: Number of input tokens
        completion_tokens: Number of output tokens
        agent_id: Optional agent ID
        session_id: Optional session/conversation ID
        request_type: Type of request (chat, workflow, summary, etc.)

    Returns:
        TokenUsage record if logged, None if tracking disabled
    """
    try:
        # Check if tracking is enabled
        if not company_settings_service.should_track_tokens(db, company_id):
            return None

        # Calculate total tokens and cost
        total_tokens = prompt_tokens + completion_tokens
        estimated_cost_cents = calculate_cost_cents(provider, model_name, prompt_tokens, completion_tokens)

        # Create usage record
        usage = TokenUsage(
            company_id=company_id,
            agent_id=agent_id,
            session_id=session_id,
            provider=provider.lower(),
            model_name=model_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            estimated_cost_cents=estimated_cost_cents,
            request_type=request_type
        )

        db.add(usage)
        db.commit()
        db.refresh(usage)

        logger.debug(
            f"[TokenUsage] Logged: provider={provider}, model={model_name}, "
            f"tokens={total_tokens}, cost=${estimated_cost_cents/100:.4f}"
        )

        # Check for budget alerts
        check_and_trigger_alerts(db, company_id, agent_id)

        return usage

    except Exception as e:
        logger.error(f"[TokenUsage] Failed to log usage: {e}")
        db.rollback()
        return None


def get_usage_by_session(
    db: Session,
    session_id: str,
    company_id: Optional[int] = None
) -> List[TokenUsage]:
    """
    Get all token usage records for a session.

    Args:
        db: Database session
        session_id: Conversation session ID
        company_id: Optional company filter

    Returns:
        List of TokenUsage records
    """
    query = db.query(TokenUsage).filter(TokenUsage.session_id == session_id)

    if company_id:
        query = query.filter(TokenUsage.company_id == company_id)

    return query.order_by(TokenUsage.created_at).all()


def get_usage_by_agent(
    db: Session,
    agent_id: int,
    company_id: Optional[int] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None
) -> Dict[str, Any]:
    """
    Get aggregated token usage for an agent.

    Args:
        db: Database session
        agent_id: Agent ID
        company_id: Optional company filter
        start_date: Start of time range
        end_date: End of time range

    Returns:
        Dictionary with usage statistics
    """
    query = db.query(TokenUsage).filter(TokenUsage.agent_id == agent_id)

    if company_id:
        query = query.filter(TokenUsage.company_id == company_id)

    if start_date:
        query = query.filter(TokenUsage.created_at >= start_date)

    if end_date:
        query = query.filter(TokenUsage.created_at <= end_date)

    # Aggregate
    result = db.query(
        func.sum(TokenUsage.prompt_tokens).label('prompt_tokens'),
        func.sum(TokenUsage.completion_tokens).label('completion_tokens'),
        func.sum(TokenUsage.total_tokens).label('total_tokens'),
        func.sum(TokenUsage.estimated_cost_cents).label('cost_cents'),
        func.count(TokenUsage.id).label('request_count')
    ).filter(
        TokenUsage.agent_id == agent_id
    )

    if company_id:
        result = result.filter(TokenUsage.company_id == company_id)
    if start_date:
        result = result.filter(TokenUsage.created_at >= start_date)
    if end_date:
        result = result.filter(TokenUsage.created_at <= end_date)

    row = result.first()

    return {
        "agent_id": agent_id,
        "prompt_tokens": row.prompt_tokens or 0,
        "completion_tokens": row.completion_tokens or 0,
        "total_tokens": row.total_tokens or 0,
        "estimated_cost_usd": (row.cost_cents or 0) / 100,
        "request_count": row.request_count or 0
    }


def get_usage_stats(
    db: Session,
    company_id: int,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None
) -> Dict[str, Any]:
    """
    Get comprehensive usage statistics for a company.

    Args:
        db: Database session
        company_id: Company ID
        start_date: Start of time range (defaults to start of current month)
        end_date: End of time range (defaults to now)

    Returns:
        Dictionary with usage statistics
    """
    # Default to current month
    if not start_date:
        now = datetime.utcnow()
        start_date = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    if not end_date:
        end_date = datetime.utcnow()

    # Base query
    base_filter = [
        TokenUsage.company_id == company_id,
        TokenUsage.created_at >= start_date,
        TokenUsage.created_at <= end_date
    ]

    # Total stats
    totals = db.query(
        func.sum(TokenUsage.prompt_tokens).label('prompt_tokens'),
        func.sum(TokenUsage.completion_tokens).label('completion_tokens'),
        func.sum(TokenUsage.total_tokens).label('total_tokens'),
        func.sum(TokenUsage.estimated_cost_cents).label('cost_cents'),
        func.count(TokenUsage.id).label('request_count')
    ).filter(*base_filter).first()

    # By provider
    by_provider = db.query(
        TokenUsage.provider,
        func.sum(TokenUsage.total_tokens).label('tokens'),
        func.sum(TokenUsage.estimated_cost_cents).label('cost_cents')
    ).filter(*base_filter).group_by(TokenUsage.provider).all()

    # By agent
    by_agent = db.query(
        TokenUsage.agent_id,
        Agent.name.label('agent_name'),
        func.sum(TokenUsage.total_tokens).label('tokens'),
        func.sum(TokenUsage.estimated_cost_cents).label('cost_cents')
    ).join(Agent, Agent.id == TokenUsage.agent_id, isouter=True
    ).filter(*base_filter).group_by(TokenUsage.agent_id, Agent.name).all()

    # By model
    by_model = db.query(
        TokenUsage.provider,
        TokenUsage.model_name,
        func.sum(TokenUsage.total_tokens).label('tokens'),
        func.sum(TokenUsage.estimated_cost_cents).label('cost_cents')
    ).filter(*base_filter).group_by(TokenUsage.provider, TokenUsage.model_name).all()

    return {
        "total_tokens": totals.total_tokens or 0,
        "prompt_tokens": totals.prompt_tokens or 0,
        "completion_tokens": totals.completion_tokens or 0,
        "estimated_cost_usd": (totals.cost_cents or 0) / 100,
        "request_count": totals.request_count or 0,
        "by_provider": {
            p.provider: {
                "tokens": p.tokens or 0,
                "cost_usd": (p.cost_cents or 0) / 100
            } for p in by_provider
        },
        "by_agent": [
            {
                "agent_id": a.agent_id,
                "name": a.agent_name or "Unknown",
                "tokens": a.tokens or 0,
                "cost_usd": (a.cost_cents or 0) / 100
            } for a in by_agent if a.agent_id
        ],
        "by_model": [
            {
                "provider": m.provider,
                "model": m.model_name,
                "tokens": m.tokens or 0,
                "cost_usd": (m.cost_cents or 0) / 100
            } for m in by_model
        ],
        "period": {
            "start": start_date.isoformat(),
            "end": end_date.isoformat()
        }
    }


def get_daily_usage(
    db: Session,
    company_id: int,
    days: int = 30
) -> List[Dict[str, Any]]:
    """
    Get daily token usage for charting.

    Args:
        db: Database session
        company_id: Company ID
        days: Number of days to include

    Returns:
        List of daily usage records
    """
    start_date = datetime.utcnow() - timedelta(days=days)

    daily = db.query(
        func.date(TokenUsage.created_at).label('date'),
        func.sum(TokenUsage.total_tokens).label('tokens'),
        func.sum(TokenUsage.estimated_cost_cents).label('cost_cents'),
        func.count(TokenUsage.id).label('requests')
    ).filter(
        TokenUsage.company_id == company_id,
        TokenUsage.created_at >= start_date
    ).group_by(
        func.date(TokenUsage.created_at)
    ).order_by(
        func.date(TokenUsage.created_at)
    ).all()

    return [
        {
            "date": str(d.date),
            "tokens": d.tokens or 0,
            "cost_usd": (d.cost_cents or 0) / 100,
            "requests": d.requests or 0
        } for d in daily
    ]


def get_monthly_spend(db: Session, company_id: int) -> int:
    """
    Get current month's spending in cents.

    Args:
        db: Database session
        company_id: Company ID

    Returns:
        Total spending in cents for current month
    """
    now = datetime.utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    result = db.query(
        func.sum(TokenUsage.estimated_cost_cents)
    ).filter(
        TokenUsage.company_id == company_id,
        TokenUsage.created_at >= month_start
    ).scalar()

    return result or 0


def check_and_trigger_alerts(
    db: Session,
    company_id: int,
    agent_id: Optional[int] = None
) -> Optional[UsageAlert]:
    """
    Check if any budget thresholds have been exceeded and create alerts.

    Args:
        db: Database session
        company_id: Company ID
        agent_id: Optional agent ID for agent-specific limits

    Returns:
        Created alert if threshold exceeded, None otherwise
    """
    try:
        budget_settings = company_settings_service.get_budget_settings(db, company_id)

        if not budget_settings["alerts_enabled"]:
            return None

        monthly_budget = budget_settings["monthly_budget_cents"]
        if not monthly_budget:
            return None

        current_spend = get_monthly_spend(db, company_id)
        threshold_percent = budget_settings["alert_threshold_percent"]
        threshold_value = int(monthly_budget * threshold_percent / 100)

        # Check if we've already sent an alert for this threshold this month
        now = datetime.utcnow()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        # Check for budget exceeded (100%)
        if current_spend >= monthly_budget:
            existing = db.query(UsageAlert).filter(
                UsageAlert.company_id == company_id,
                UsageAlert.alert_type == "budget_exceeded",
                UsageAlert.created_at >= month_start
            ).first()

            if not existing:
                alert = UsageAlert(
                    company_id=company_id,
                    alert_type="budget_exceeded",
                    threshold_value=monthly_budget,
                    current_value=current_spend,
                    message=f"Monthly budget exceeded! Current spend: ${current_spend/100:.2f} (Budget: ${monthly_budget/100:.2f})"
                )
                db.add(alert)
                db.commit()
                db.refresh(alert)
                logger.warning(f"[UsageAlert] Budget exceeded for company {company_id}")
                return alert

        # Check for budget warning (threshold %)
        elif current_spend >= threshold_value:
            existing = db.query(UsageAlert).filter(
                UsageAlert.company_id == company_id,
                UsageAlert.alert_type == "budget_warning",
                UsageAlert.created_at >= month_start
            ).first()

            if not existing:
                alert = UsageAlert(
                    company_id=company_id,
                    alert_type="budget_warning",
                    threshold_value=threshold_value,
                    current_value=current_spend,
                    message=f"Approaching monthly budget ({threshold_percent}%). Current spend: ${current_spend/100:.2f} (Budget: ${monthly_budget/100:.2f})"
                )
                db.add(alert)
                db.commit()
                db.refresh(alert)
                logger.info(f"[UsageAlert] Budget warning for company {company_id}")
                return alert

        return None

    except Exception as e:
        logger.error(f"[UsageAlert] Failed to check alerts: {e}")
        return None


def get_active_alerts(
    db: Session,
    company_id: int,
    include_acknowledged: bool = False
) -> List[UsageAlert]:
    """
    Get active (unacknowledged) alerts for a company.

    Args:
        db: Database session
        company_id: Company ID
        include_acknowledged: Include acknowledged alerts

    Returns:
        List of UsageAlert records
    """
    query = db.query(UsageAlert).filter(UsageAlert.company_id == company_id)

    if not include_acknowledged:
        query = query.filter(UsageAlert.acknowledged == False)

    return query.order_by(desc(UsageAlert.created_at)).all()


def acknowledge_alert(
    db: Session,
    alert_id: int,
    user_id: int
) -> Optional[UsageAlert]:
    """
    Acknowledge an alert.

    Args:
        db: Database session
        alert_id: Alert ID
        user_id: User acknowledging the alert

    Returns:
        Updated UsageAlert or None
    """
    alert = db.query(UsageAlert).filter(UsageAlert.id == alert_id).first()

    if alert:
        alert.acknowledged = True
        alert.acknowledged_at = datetime.utcnow()
        alert.acknowledged_by = user_id
        db.commit()
        db.refresh(alert)

    return alert


def get_usage_records(
    db: Session,
    company_id: int,
    agent_id: Optional[int] = None,
    provider: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    limit: int = 100,
    offset: int = 0
) -> List[TokenUsage]:
    """
    Get paginated token usage records with filters.

    Args:
        db: Database session
        company_id: Company ID
        agent_id: Optional agent filter
        provider: Optional provider filter
        start_date: Start of time range
        end_date: End of time range
        limit: Maximum records to return
        offset: Pagination offset

    Returns:
        List of TokenUsage records
    """
    query = db.query(TokenUsage).filter(TokenUsage.company_id == company_id)

    if agent_id:
        query = query.filter(TokenUsage.agent_id == agent_id)

    if provider:
        query = query.filter(TokenUsage.provider == provider.lower())

    if start_date:
        query = query.filter(TokenUsage.created_at >= start_date)

    if end_date:
        query = query.filter(TokenUsage.created_at <= end_date)

    return query.order_by(desc(TokenUsage.created_at)).offset(offset).limit(limit).all()
