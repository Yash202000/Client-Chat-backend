from pydantic import BaseModel, field_validator
from typing import Optional, List, Any, Dict
from datetime import datetime

VALID_ENTITY_TYPES = {"ticket", "lead", "deal"}
VALID_TRIGGERS = {"on_create", "on_transition", "both"}
VALID_ACTION_TYPES = {
    "assign_to_user", "assign_round_robin", "assign_by_skill",
    "assign_to_queue", "no_action",
}
VALID_OPERATORS = {"eq", "neq", "in", "not_in", "contains", "gte", "lte", "exists", "not_exists"}


class RoutingCondition(BaseModel):
    field: str        # e.g. "priority", "source", "custom_fields.tier", "tags"
    operator: str     # eq|neq|in|not_in|contains|gte|lte|exists|not_exists
    value: Optional[Any] = None  # not required for exists/not_exists

    @field_validator("operator")
    @classmethod
    def validate_operator(cls, v):
        if v not in VALID_OPERATORS:
            raise ValueError(f"operator must be one of {VALID_OPERATORS}")
        return v


class RoutingRuleBase(BaseModel):
    entity_type: str
    name: str
    priority: int = 0
    trigger: str = "on_create"
    trigger_transition_id: Optional[int] = None
    conditions: Optional[List[RoutingCondition]] = None
    action_type: str = "assign_to_user"
    action_config: Optional[Dict[str, Any]] = None
    is_active: bool = True

    @field_validator("entity_type")
    @classmethod
    def validate_entity_type(cls, v):
        if v not in VALID_ENTITY_TYPES:
            raise ValueError(f"entity_type must be one of {VALID_ENTITY_TYPES}")
        return v

    @field_validator("trigger")
    @classmethod
    def validate_trigger(cls, v):
        if v not in VALID_TRIGGERS:
            raise ValueError(f"trigger must be one of {VALID_TRIGGERS}")
        return v

    @field_validator("action_type")
    @classmethod
    def validate_action_type(cls, v):
        if v not in VALID_ACTION_TYPES:
            raise ValueError(f"action_type must be one of {VALID_ACTION_TYPES}")
        return v


class RoutingRuleCreate(RoutingRuleBase):
    pass


class RoutingRuleUpdate(BaseModel):
    name: Optional[str] = None
    priority: Optional[int] = None
    trigger: Optional[str] = None
    trigger_transition_id: Optional[int] = None
    conditions: Optional[List[RoutingCondition]] = None
    action_type: Optional[str] = None
    action_config: Optional[Dict[str, Any]] = None
    is_active: Optional[bool] = None


class RoutingRuleOut(RoutingRuleBase):
    id: int
    company_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
