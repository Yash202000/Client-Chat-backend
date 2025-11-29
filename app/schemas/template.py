from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime


class TemplateBase(BaseModel):
    """Base schema for template data"""
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    template_type: str = Field(..., pattern="^(email|sms|whatsapp|voice)$")

    # Email fields
    subject: Optional[str] = Field(None, max_length=500)
    body: Optional[str] = None
    html_body: Optional[str] = None

    # Voice fields
    voice_script: Optional[str] = None
    tts_voice_id: Optional[str] = None

    # WhatsApp fields
    whatsapp_template_name: Optional[str] = None
    whatsapp_template_params: Optional[Dict[str, Any]] = None

    # Metadata
    personalization_tokens: Optional[List[str]] = []
    tags: Optional[List[str]] = []


class TemplateCreate(TemplateBase):
    """Schema for creating a new template"""
    is_ai_generated: Optional[bool] = False


class TemplateUpdate(BaseModel):
    """Schema for updating an existing template"""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    template_type: Optional[str] = Field(None, pattern="^(email|sms|whatsapp|voice)$")

    # Email fields
    subject: Optional[str] = Field(None, max_length=500)
    body: Optional[str] = None
    html_body: Optional[str] = None

    # Voice fields
    voice_script: Optional[str] = None
    tts_voice_id: Optional[str] = None

    # WhatsApp fields
    whatsapp_template_name: Optional[str] = None
    whatsapp_template_params: Optional[Dict[str, Any]] = None

    # Metadata
    personalization_tokens: Optional[List[str]] = None
    tags: Optional[List[str]] = None
    is_ai_generated: Optional[bool] = None


class Template(TemplateBase):
    """Schema for template response"""
    id: int
    company_id: int
    created_by_user_id: Optional[int] = None
    is_ai_generated: bool = False
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class TemplateList(BaseModel):
    """Schema for paginated template list"""
    templates: List[Template]
    total: int
    page: int = 1
    page_size: int = 20


class TemplateDuplicate(BaseModel):
    """Schema for duplicating a template"""
    new_name: str = Field(..., min_length=1, max_length=255)


# AI Generation Schemas
class AIGenerateRequest(BaseModel):
    """Request schema for AI template generation"""
    credential_id: int = Field(..., description="ID of the vault credential to use for LLM")
    model: Optional[str] = Field(None, description="Model ID to use (defaults to provider's default)")
    template_type: str = Field(..., pattern="^(email|sms|whatsapp|voice)$")
    prompt: str = Field(..., min_length=10, max_length=2000)
    tone: Optional[str] = Field("professional", pattern="^(professional|friendly|casual|formal|persuasive)$")
    target_audience: Optional[str] = None
    campaign_goal: Optional[str] = None
    include_cta: Optional[bool] = True
    language: Optional[str] = "en"


class AIGenerateResponse(BaseModel):
    """Response schema for AI generated template"""
    subject: Optional[str] = None
    body: str
    html_body: Optional[str] = None
    personalization_tokens: List[str] = []
    suggestions: Optional[List[str]] = None


class AISuggestSubjectsRequest(BaseModel):
    """Request schema for AI subject line suggestions"""
    credential_id: int = Field(..., description="ID of the vault credential to use for LLM")
    model: Optional[str] = Field(None, description="Model ID to use")
    body: str = Field(..., min_length=10)
    count: Optional[int] = Field(5, ge=1, le=10)
    tone: Optional[str] = "professional"


class AISuggestSubjectsResponse(BaseModel):
    """Response schema for AI subject line suggestions"""
    subjects: List[str]


class AIImproveRequest(BaseModel):
    """Request schema for AI content improvement"""
    credential_id: int = Field(..., description="ID of the vault credential to use for LLM")
    model: Optional[str] = Field(None, description="Model ID to use")
    content: str = Field(..., min_length=10)
    content_type: str = Field("body", pattern="^(subject|body|html_body|voice_script)$")
    improvements: List[str] = Field(..., min_length=1)  # e.g., ["more engaging", "shorter", "add urgency"]


class AIImproveResponse(BaseModel):
    """Response schema for AI improved content"""
    improved_content: str
    changes_made: List[str]


class AIVariantsRequest(BaseModel):
    """Request schema for generating A/B test variants"""
    credential_id: int = Field(..., description="ID of the vault credential to use for LLM")
    model: Optional[str] = Field(None, description="Model ID to use")
    template_id: int
    variant_count: Optional[int] = Field(2, ge=1, le=5)
    variation_type: Optional[str] = Field("subject", pattern="^(subject|body|both)$")


class AIVariantsResponse(BaseModel):
    """Response schema for A/B test variants"""
    variants: List[Dict[str, Any]]  # List of template-like objects with variations


class AIProvidersResponse(BaseModel):
    """Response schema for available AI providers"""
    providers: List[Dict[str, Any]]
