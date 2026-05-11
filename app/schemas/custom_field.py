from pydantic import BaseModel, field_validator
from typing import Optional, List, Any, Dict
from datetime import datetime

VALID_ENTITY_TYPES = {"ticket", "lead", "deal", "contact"}
VALID_FIELD_TYPES = {
    "text", "textarea", "number", "decimal", "boolean",
    "date", "datetime", "dropdown", "multi_select",
    "user_picker", "url", "email", "phone", "coordinates", "hierarchy_node",
}


class FieldOption(BaseModel):
    value: str
    label: str
    color: Optional[str] = None


class CustomFieldDefinitionBase(BaseModel):
    entity_type: str
    name: str
    label: str
    field_type: str = "text"
    options: Optional[List[FieldOption]] = None
    required: bool = False
    default_value: Optional[Any] = None
    position: int = 0
    is_active: bool = True
    group_name: Optional[str] = None
    is_global: bool = True

    @field_validator("entity_type")
    @classmethod
    def validate_entity_type(cls, v):
        if v not in VALID_ENTITY_TYPES:
            raise ValueError(f"entity_type must be one of {VALID_ENTITY_TYPES}")
        return v

    @field_validator("field_type")
    @classmethod
    def validate_field_type(cls, v):
        if v not in VALID_FIELD_TYPES:
            raise ValueError(f"field_type must be one of {VALID_FIELD_TYPES}")
        return v

    @field_validator("name")
    @classmethod
    def validate_name(cls, v):
        import re
        if not re.match(r'^[a-z][a-z0-9_]*$', v):
            raise ValueError("name must be lowercase alphanumeric + underscore, starting with a letter")
        return v


class CustomFieldDefinitionCreate(CustomFieldDefinitionBase):
    pass


class CustomFieldDefinitionUpdate(BaseModel):
    label: Optional[str] = None
    field_type: Optional[str] = None
    options: Optional[List[FieldOption]] = None
    required: Optional[bool] = None
    default_value: Optional[Any] = None
    position: Optional[int] = None
    is_active: Optional[bool] = None
    group_name: Optional[str] = None
    is_global: Optional[bool] = None


class CustomFieldDefinitionOut(CustomFieldDefinitionBase):
    id: int
    company_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ── Project config schemas ────────────────────────────────────────────────────

class CustomFieldProjectConfigUpsert(BaseModel):
    visible: bool = True
    required: Optional[bool] = None    # None = inherit from field def
    position: Optional[int] = None     # None = inherit
    group_name: Optional[str] = None   # None = inherit


class CustomFieldProjectConfigOut(BaseModel):
    id: int
    field_id: int
    project_id: int
    visible: bool
    required: Optional[bool]
    position: Optional[int]
    group_name: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ── Value validation helper schemas ──────────────────────────────────────────

class CustomFieldValueValidation(BaseModel):
    """Used internally to validate a dict of field values against definitions."""
    field_values: Dict[str, Any]
