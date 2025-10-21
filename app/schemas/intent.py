from typing import Optional, List, Dict, Any
from pydantic import BaseModel
from datetime import datetime


# Entity Schemas
class EntityBase(BaseModel):
    name: str
    description: Optional[str] = None
    entity_type: str = "text"  # text, number, email, date, phone, custom
    extraction_method: str = "llm"  # llm, regex, keyword
    validation_regex: Optional[str] = None
    example_values: List[str] = []


class EntityCreate(EntityBase):
    company_id: int


class EntityUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    entity_type: Optional[str] = None
    extraction_method: Optional[str] = None
    validation_regex: Optional[str] = None
    example_values: Optional[List[str]] = None
    is_active: Optional[bool] = None


class EntityResponse(EntityBase):
    id: int
    company_id: int
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# Intent Schemas
class IntentBase(BaseModel):
    name: str
    description: Optional[str] = None
    intent_category: Optional[str] = None
    training_phrases: List[str] = []
    keywords: List[str] = []
    trigger_workflow_id: Optional[int] = None
    auto_trigger_enabled: bool = True
    require_agent_approval: bool = False
    confidence_threshold: float = 0.7
    min_confidence_auto_trigger: float = 0.7
    priority: int = 0


class IntentCreate(IntentBase):
    company_id: int
    entity_ids: List[int] = []  # IDs of entities to associate


class IntentUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    intent_category: Optional[str] = None
    training_phrases: Optional[List[str]] = None
    keywords: Optional[List[str]] = None
    trigger_workflow_id: Optional[int] = None
    auto_trigger_enabled: Optional[bool] = None
    require_agent_approval: Optional[bool] = None
    confidence_threshold: Optional[float] = None
    min_confidence_auto_trigger: Optional[float] = None
    priority: Optional[int] = None
    is_active: Optional[bool] = None
    entity_ids: Optional[List[int]] = None


class IntentResponse(IntentBase):
    id: int
    company_id: int
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class IntentWithEntities(IntentResponse):
    entities: List[EntityResponse] = []

    class Config:
        from_attributes = True


# Intent Match Schemas
class IntentMatchResponse(BaseModel):
    id: int
    conversation_id: str
    intent_id: int
    intent_name: Optional[str] = None
    message_text: str
    confidence_score: float
    matched_method: str
    extracted_entities: Dict[str, Any] = {}
    triggered_workflow_id: Optional[int] = None
    workflow_executed: bool
    execution_status: Optional[str] = None
    matched_at: datetime

    class Config:
        from_attributes = True


# Test Intent Request
class TestIntentRequest(BaseModel):
    test_message: str


class TestIntentResponse(BaseModel):
    matched: bool
    intent_id: Optional[int] = None
    intent_name: Optional[str] = None
    confidence: float
    matched_method: Optional[str] = None
    extracted_entities: Dict[str, Any] = {}
    reasoning: str


# Conversation Tag Schemas
class ConversationTagCreate(BaseModel):
    conversation_id: str
    tag: str
    added_by_user_id: Optional[int] = None


class ConversationTagResponse(BaseModel):
    id: int
    conversation_id: str
    tag: str
    added_by_user_id: Optional[int] = None
    added_by_system: bool
    added_at: datetime

    class Config:
        from_attributes = True
