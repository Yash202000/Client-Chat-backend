from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum
import re


# =============================================================================
# Enums
# =============================================================================

class FieldType(str, Enum):
    TEXT = "text"
    RICH_TEXT = "rich_text"
    NUMBER = "number"
    BOOLEAN = "boolean"
    DATE = "date"
    DATETIME = "datetime"
    SELECT = "select"
    MEDIA = "media"
    AUDIO = "audio"
    VIDEO = "video"
    FILE = "file"
    RELATION = "relation"
    TAGS = "tags"
    URL = "url"
    EMAIL = "email"
    JSON = "json"


class ContentStatus(str, Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class ContentVisibility(str, Enum):
    PRIVATE = "private"
    COMPANY = "company"
    MARKETPLACE = "marketplace"
    PUBLIC = "public"


class ExportFormat(str, Enum):
    JSON = "json"
    CSV = "csv"
    PDF = "pdf"


class ExportStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


# =============================================================================
# Field Schema Definition
# =============================================================================

class FieldDefinition(BaseModel):
    """Defines a single field in a content type schema."""
    slug: str = Field(..., min_length=1, max_length=50)
    name: str = Field(..., min_length=1, max_length=100)
    type: FieldType
    required: bool = False
    searchable: bool = False
    settings: Optional[Dict[str, Any]] = None  # type-specific settings

    @field_validator('slug')
    @classmethod
    def validate_slug(cls, v):
        if not re.match(r'^[a-z][a-z0-9_]*$', v):
            raise ValueError('Slug must start with a letter and contain only lowercase letters, numbers, and underscores')
        return v


# =============================================================================
# Content Type Schemas
# =============================================================================

class ContentTypeBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    slug: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    icon: Optional[str] = None
    field_schema: List[FieldDefinition] = []
    allow_public_publish: bool = True

    @field_validator('slug')
    @classmethod
    def validate_slug(cls, v):
        if not re.match(r'^[a-z][a-z0-9_-]*$', v):
            raise ValueError('Slug must start with a letter and contain only lowercase letters, numbers, hyphens, and underscores')
        return v


class ContentTypeCreate(ContentTypeBase):
    knowledge_base_id: Optional[int] = None


class ContentTypeUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    icon: Optional[str] = None
    field_schema: Optional[List[FieldDefinition]] = None
    allow_public_publish: Optional[bool] = None


class ContentTypeResponse(ContentTypeBase):
    id: int
    company_id: int
    knowledge_base_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# =============================================================================
# Content Item Schemas
# =============================================================================

class ContentItemBase(BaseModel):
    data: Dict[str, Any] = {}
    status: ContentStatus = ContentStatus.DRAFT
    visibility: ContentVisibility = ContentVisibility.PRIVATE


class ContentItemCreate(ContentItemBase):
    content_type_id: Optional[int] = None  # Can be inferred from URL
    knowledge_base_id: Optional[int] = None
    category_ids: Optional[List[int]] = None


class ContentItemUpdate(BaseModel):
    data: Optional[Dict[str, Any]] = None
    status: Optional[ContentStatus] = None
    visibility: Optional[ContentVisibility] = None
    category_ids: Optional[List[int]] = None


class ContentItemCategoryInfo(BaseModel):
    """Simplified category info for content item response."""
    id: int
    name: str
    slug: str

    class Config:
        from_attributes = True


class ContentItemResponse(ContentItemBase):
    id: int
    content_type_id: int
    company_id: int
    knowledge_base_id: Optional[int] = None
    is_featured: bool = False
    download_count: int = 0
    rating: Optional[float] = None
    version: int = 1
    chroma_doc_id: Optional[str] = None
    created_by: Optional[int] = None
    updated_by: Optional[int] = None
    published_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    categories: List[ContentItemCategoryInfo] = []

    class Config:
        from_attributes = True


class ContentItemListResponse(BaseModel):
    """Paginated list of content items."""
    items: List[ContentItemResponse]
    total: int
    page: int
    page_size: int
    pages: int


# =============================================================================
# Content Media Schemas
# =============================================================================

class ContentMediaBase(BaseModel):
    alt_text: Optional[str] = None
    caption: Optional[str] = None


class ContentMediaCreate(ContentMediaBase):
    # File will be uploaded separately, these are set by the system
    pass


class ContentMediaUpdate(BaseModel):
    alt_text: Optional[str] = None
    caption: Optional[str] = None


class ContentMediaResponse(ContentMediaBase):
    id: int
    company_id: int
    filename: str
    original_filename: Optional[str] = None
    mime_type: Optional[str] = None
    file_size: Optional[int] = None
    media_type: Optional[str] = None
    s3_bucket: Optional[str] = None
    s3_key: str
    thumbnail_s3_key: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    duration: Optional[int] = None
    usage_count: int = 0
    uploaded_by: Optional[int] = None
    created_at: datetime
    url: Optional[str] = None  # Pre-signed URL, computed

    class Config:
        from_attributes = True


# =============================================================================
# Content Category Schemas
# =============================================================================

class ContentCategoryBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    slug: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    icon: Optional[str] = None
    display_order: int = 0

    @field_validator('slug')
    @classmethod
    def validate_slug(cls, v):
        if not re.match(r'^[a-z][a-z0-9_-]*$', v):
            raise ValueError('Slug must start with a letter and contain only lowercase letters, numbers, hyphens, and underscores')
        return v


class ContentCategoryCreate(ContentCategoryBase):
    parent_id: Optional[int] = None
    knowledge_base_id: Optional[int] = None


class ContentCategoryUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    slug: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    icon: Optional[str] = None
    parent_id: Optional[int] = None
    display_order: Optional[int] = None


class ContentCategoryResponse(ContentCategoryBase):
    id: int
    company_id: int
    knowledge_base_id: Optional[int] = None
    parent_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime
    children: Optional[List['ContentCategoryResponse']] = None

    class Config:
        from_attributes = True


# =============================================================================
# Content Tag Schemas
# =============================================================================

class ContentTagBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    slug: str = Field(..., min_length=1, max_length=100)
    color: Optional[str] = Field(None, pattern=r'^#[0-9A-Fa-f]{6}$')

    @field_validator('slug')
    @classmethod
    def validate_slug(cls, v):
        if not re.match(r'^[a-z][a-z0-9_-]*$', v):
            raise ValueError('Slug must start with a letter and contain only lowercase letters, numbers, hyphens, and underscores')
        return v


class ContentTagCreate(ContentTagBase):
    pass


class ContentTagUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    color: Optional[str] = Field(None, pattern=r'^#[0-9A-Fa-f]{6}$')


class ContentTagResponse(ContentTagBase):
    id: int
    company_id: int
    usage_count: int = 0
    created_at: datetime

    class Config:
        from_attributes = True


# =============================================================================
# Publishing Schemas
# =============================================================================

class VisibilityUpdate(BaseModel):
    visibility: ContentVisibility


class ContentCopyResponse(BaseModel):
    id: int
    original_item_id: int
    original_company_id: int
    copied_item_id: int
    copied_by_company_id: int
    copied_by_user_id: Optional[int] = None
    copied_at: datetime

    class Config:
        from_attributes = True


# =============================================================================
# API Token Schemas
# =============================================================================

class ContentApiTokenBase(BaseModel):
    name: Optional[str] = None
    can_read: bool = True
    can_search: bool = True
    rate_limit: int = 100
    expires_at: Optional[datetime] = None


class ContentApiTokenCreate(ContentApiTokenBase):
    knowledge_base_id: Optional[int] = None


class ContentApiTokenResponse(ContentApiTokenBase):
    id: int
    company_id: int
    knowledge_base_id: Optional[int] = None
    token: str
    is_active: bool = True
    last_used_at: Optional[datetime] = None
    request_count: int = 0
    created_at: datetime

    class Config:
        from_attributes = True


# =============================================================================
# Export Schemas
# =============================================================================

class ContentExportCreate(BaseModel):
    format: ExportFormat = ExportFormat.JSON
    knowledge_base_id: Optional[int] = None
    content_type_slug: Optional[str] = None
    filter_criteria: Optional[Dict[str, Any]] = None


class ContentExportResponse(BaseModel):
    id: int
    company_id: int
    knowledge_base_id: Optional[int] = None
    format: str
    status: str
    s3_key: Optional[str] = None
    file_size: Optional[int] = None
    item_count: Optional[int] = None
    requested_by: Optional[int] = None
    completed_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    created_at: datetime
    download_url: Optional[str] = None  # Pre-signed URL, computed

    class Config:
        from_attributes = True


# =============================================================================
# Search Schemas
# =============================================================================

class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    content_type_slug: Optional[str] = None
    knowledge_base_id: Optional[int] = None
    limit: int = Field(10, ge=1, le=100)


class SearchResult(BaseModel):
    id: int
    content_type_slug: str
    data: Dict[str, Any]
    score: float
    highlights: Optional[Dict[str, str]] = None


class SearchResponse(BaseModel):
    results: List[SearchResult]
    total: int
    query: str


# =============================================================================
# Marketplace Schemas
# =============================================================================

class MarketplaceItemResponse(BaseModel):
    id: int
    content_type_slug: str
    content_type_name: str
    data: Dict[str, Any]
    company_name: str
    is_featured: bool = False
    download_count: int = 0
    rating: Optional[float] = None
    created_at: datetime

    class Config:
        from_attributes = True


class MarketplaceListResponse(BaseModel):
    items: List[MarketplaceItemResponse]
    total: int
    page: int
    page_size: int
