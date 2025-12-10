from pydantic import BaseModel, Field, validator
from typing import Optional, List
from datetime import datetime


class MessageTemplateBase(BaseModel):
    """Base schema for message template"""
    name: str = Field(..., min_length=1, max_length=255, description="Display name of the template")
    shortcut: str = Field(..., min_length=1, max_length=50, description="Slash command shortcut (e.g., 'greeting')")
    content: str = Field(..., min_length=1, description="Template content with variables")
    tags: Optional[List[str]] = Field(default=[], description="Tags for organizing templates")
    scope: str = Field(default="personal", description="Visibility scope: 'personal' or 'shared'")


class MessageTemplateCreate(MessageTemplateBase):
    """Schema for creating a new message template"""

    @validator('shortcut')
    def validate_shortcut(cls, v):
        """Ensure shortcut is alphanumeric with underscores/hyphens only"""
        if not v:
            raise ValueError('Shortcut cannot be empty')
        # Remove allowed characters and check if anything remains
        cleaned = v.replace('_', '').replace('-', '')
        if not cleaned.isalnum():
            raise ValueError('Shortcut must be alphanumeric (with _ or - allowed)')
        return v.lower()

    @validator('scope')
    def validate_scope(cls, v):
        """Ensure scope is valid"""
        if v not in ['personal', 'shared']:
            raise ValueError('Scope must be either "personal" or "shared"')
        return v

    @validator('tags')
    def validate_tags(cls, v):
        """Clean up tags"""
        if v is None:
            return []
        # Remove empty strings and duplicates
        return list(set([tag.strip() for tag in v if tag and tag.strip()]))


class MessageTemplateUpdate(BaseModel):
    """Schema for updating a message template"""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    shortcut: Optional[str] = Field(None, min_length=1, max_length=50)
    content: Optional[str] = Field(None, min_length=1)
    tags: Optional[List[str]] = None
    scope: Optional[str] = None

    @validator('shortcut')
    def validate_shortcut(cls, v):
        """Ensure shortcut is alphanumeric with underscores/hyphens only"""
        if v is None:
            return v
        cleaned = v.replace('_', '').replace('-', '')
        if not cleaned.isalnum():
            raise ValueError('Shortcut must be alphanumeric (with _ or - allowed)')
        return v.lower()

    @validator('scope')
    def validate_scope(cls, v):
        """Ensure scope is valid"""
        if v is not None and v not in ['personal', 'shared']:
            raise ValueError('Scope must be either "personal" or "shared"')
        return v

    @validator('tags')
    def validate_tags(cls, v):
        """Clean up tags"""
        if v is None:
            return None
        return list(set([tag.strip() for tag in v if tag and tag.strip()]))


class MessageTemplate(MessageTemplateBase):
    """Full message template schema with all fields"""
    id: int
    company_id: int
    created_by_user_id: int
    usage_count: int
    last_used_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class MessageTemplateList(BaseModel):
    """Paginated list of message templates"""
    templates: List[MessageTemplate]
    total: int
    page: int
    page_size: int


class TemplateSearchResult(BaseModel):
    """Search result for slash command autocomplete"""
    id: int
    shortcut: str
    name: str
    content: str
    preview: str  # First 100 chars of content
    scope: str
    tags: List[str]

    class Config:
        from_attributes = True


class ReplaceVariablesRequest(BaseModel):
    """Request to replace template variables"""
    content: str = Field(..., description="Content with {{variable}} placeholders")
    session_id: Optional[str] = Field(None, description="Conversation session ID for contact context")
    agent_id: Optional[int] = Field(None, description="Agent ID for agent context")


class AvailableVariable(BaseModel):
    """Information about an available variable"""
    variable: str
    description: str


class AvailableVariables(BaseModel):
    """All available variables for templates"""
    contact_variables: List[AvailableVariable]
    agent_variables: List[AvailableVariable]
    system_variables: List[AvailableVariable]
