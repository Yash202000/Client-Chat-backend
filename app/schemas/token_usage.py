"""
Token Usage Schemas

Pydantic schemas for token usage tracking API.
"""
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime


class TokenUsageBase(BaseModel):
    """Base schema for token usage."""
    provider: str
    model_name: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost_cents: Optional[int] = None
    request_type: Optional[str] = None


class TokenUsageCreate(TokenUsageBase):
    """Schema for creating token usage record."""
    company_id: int
    agent_id: Optional[int] = None
    session_id: Optional[str] = None


class TokenUsageResponse(TokenUsageBase):
    """Schema for token usage response."""
    id: int
    company_id: int
    agent_id: Optional[int] = None
    session_id: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class TokenUsageStats(BaseModel):
    """Schema for aggregated token usage statistics."""
    total_tokens: int
    prompt_tokens: int
    completion_tokens: int
    estimated_cost_usd: float
    request_count: int
    by_provider: Dict[str, Dict[str, Any]]
    by_agent: List[Dict[str, Any]]
    by_model: List[Dict[str, Any]]
    period: Dict[str, str]


class DailyUsage(BaseModel):
    """Schema for daily usage breakdown."""
    date: str
    tokens: int
    cost_usd: float
    requests: int


class UsageAlertBase(BaseModel):
    """Base schema for usage alerts."""
    alert_type: str
    threshold_value: int
    current_value: int
    message: Optional[str] = None


class UsageAlertResponse(UsageAlertBase):
    """Schema for usage alert response."""
    id: int
    company_id: int
    agent_id: Optional[int] = None
    acknowledged: bool
    acknowledged_at: Optional[datetime] = None
    acknowledged_by: Optional[int] = None
    created_at: datetime

    class Config:
        from_attributes = True


class UsageAlertAcknowledge(BaseModel):
    """Schema for acknowledging an alert."""
    alert_id: int


class TokenTrackingSettings(BaseModel):
    """Schema for token tracking settings."""
    token_tracking_mode: str  # none, aggregated, detailed
    monthly_budget_cents: Optional[int] = None
    alert_threshold_percent: int = 80
    alert_email: Optional[str] = None
    alerts_enabled: bool = True
    per_agent_daily_limit_cents: Optional[int] = None


class TokenTrackingSettingsUpdate(BaseModel):
    """Schema for updating token tracking settings."""
    token_tracking_mode: Optional[str] = None
    monthly_budget_cents: Optional[int] = None
    alert_threshold_percent: Optional[int] = None
    alert_email: Optional[str] = None
    alerts_enabled: Optional[bool] = None
    per_agent_daily_limit_cents: Optional[int] = None
