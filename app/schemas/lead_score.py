from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from datetime import datetime


class LeadScoreBase(BaseModel):
    lead_id: int
    score_type: str  # ai_intent, engagement, demographic, behavioral, workflow, manual, combined
    score_value: int  # 0-100
    weight: Optional[float] = 1.0
    score_reason: Optional[str] = None
    score_factors: Optional[Dict[str, Any]] = None
    confidence: Optional[float] = None
    intent_matches: Optional[List[Dict[str, Any]]] = None
    scored_by_user_id: Optional[int] = None
    scored_by_agent_id: Optional[int] = None
    conversation_session_id: Optional[str] = None
    expires_at: Optional[datetime] = None
    score_metadata: Optional[Dict[str, Any]] = None


class LeadScoreCreate(LeadScoreBase):
    pass


class LeadScoreUpdate(BaseModel):
    score_value: Optional[int] = None
    weight: Optional[float] = None
    score_reason: Optional[str] = None
    score_factors: Optional[Dict[str, Any]] = None
    confidence: Optional[float] = None
    intent_matches: Optional[List[Dict[str, Any]]] = None
    expires_at: Optional[datetime] = None
    score_metadata: Optional[Dict[str, Any]] = None


class LeadScore(LeadScoreBase):
    id: int
    company_id: int
    scored_at: datetime

    class Config:
        from_attributes = True


class LeadScoreWithDetails(LeadScore):
    """Lead score with scoring agent/user details"""
    scored_by_user: Optional[Any] = None  # Will be User schema
    scored_by_agent: Optional[Any] = None  # Will be Agent schema

    class Config:
        from_attributes = True
