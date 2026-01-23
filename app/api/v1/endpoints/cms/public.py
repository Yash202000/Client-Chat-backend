from fastapi import APIRouter, Depends, HTTPException, Query, Header
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime

from app.services.cms import publishing_service, search_service
from app.core.dependencies import get_db
from app.models.content_item import ContentItem
from app.models.content_type import ContentType
from app.models.content_publishing import ContentApiToken
from app.schemas.cms import ContentStatus, ContentVisibility
from sqlalchemy import and_

router = APIRouter()


# ==================== Token Validation Dependency ====================

def get_api_token(
    db: Session = Depends(get_db),
    authorization: str = Header(..., description="API token in format: Bearer <token>")
) -> ContentApiToken:
    """Validate API token from Authorization header."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Invalid authorization header. Use: Bearer <token>"
        )

    token_string = authorization[7:]  # Remove "Bearer " prefix

    is_valid, token, error = publishing_service.validate_api_token(db, token_string)

    if not is_valid:
        raise HTTPException(status_code=401, detail=error)

    # Record usage
    publishing_service.record_token_usage(db, token)

    return token


# ==================== Response Models ====================

class PublicContentItem(BaseModel):
    id: int
    content_type_slug: str
    content_type_name: str
    data: dict
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


class PublicContentListResponse(BaseModel):
    items: List[PublicContentItem]
    total: int


class PublicSearchResult(BaseModel):
    id: int
    content_type_slug: str
    data: dict
    score: float
    highlights: dict


class PublicSearchResponse(BaseModel):
    results: List[PublicSearchResult]
    total: int
    query: str


class PublicContentTypeInfo(BaseModel):
    slug: str
    name: str
    description: Optional[str]
    icon: Optional[str]
    item_count: int


# ==================== Public API Endpoints ====================

@router.get("/content", response_model=PublicContentListResponse)
def list_public_content(
    *,
    db: Session = Depends(get_db),
    token: ContentApiToken = Depends(get_api_token),
    content_type_slug: Optional[str] = Query(None, description="Filter by content type"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200)
):
    """
    List public content items.

    Requires a valid API token with read permission.
    Only returns published content with 'public' visibility.
    """
    if not token.can_read:
        raise HTTPException(status_code=403, detail="Token does not have read permission")

    # Build query
    query = db.query(ContentItem).filter(
        and_(
            ContentItem.company_id == token.company_id,
            ContentItem.visibility == ContentVisibility.PUBLIC.value,
            ContentItem.status == ContentStatus.PUBLISHED.value
        )
    )

    # Filter by knowledge base if token is scoped
    if token.knowledge_base_id:
        query = query.filter(ContentItem.knowledge_base_id == token.knowledge_base_id)

    # Filter by content type
    if content_type_slug:
        query = query.join(ContentType).filter(ContentType.slug == content_type_slug)

    total = query.count()
    items = query.order_by(ContentItem.created_at.desc()).offset(skip).limit(limit).all()

    response_items = []
    for item in items:
        response_items.append(PublicContentItem(
            id=item.id,
            content_type_slug=item.content_type.slug if item.content_type else "",
            content_type_name=item.content_type.name if item.content_type else "",
            data=item.data,
            created_at=item.created_at,
            updated_at=item.updated_at
        ))

    return PublicContentListResponse(items=response_items, total=total)


@router.get("/content/{item_id}", response_model=PublicContentItem)
def get_public_content(
    *,
    db: Session = Depends(get_db),
    token: ContentApiToken = Depends(get_api_token),
    item_id: int
):
    """
    Get a single public content item by ID.

    Requires a valid API token with read permission.
    """
    if not token.can_read:
        raise HTTPException(status_code=403, detail="Token does not have read permission")

    # Build query
    query = db.query(ContentItem).filter(
        and_(
            ContentItem.id == item_id,
            ContentItem.company_id == token.company_id,
            ContentItem.visibility == ContentVisibility.PUBLIC.value,
            ContentItem.status == ContentStatus.PUBLISHED.value
        )
    )

    # Filter by knowledge base if token is scoped
    if token.knowledge_base_id:
        query = query.filter(ContentItem.knowledge_base_id == token.knowledge_base_id)

    item = query.first()

    if not item:
        raise HTTPException(status_code=404, detail="Content not found")

    return PublicContentItem(
        id=item.id,
        content_type_slug=item.content_type.slug if item.content_type else "",
        content_type_name=item.content_type.name if item.content_type else "",
        data=item.data,
        created_at=item.created_at,
        updated_at=item.updated_at
    )


@router.get("/content/type/{type_slug}", response_model=PublicContentListResponse)
def get_public_content_by_type(
    *,
    db: Session = Depends(get_db),
    token: ContentApiToken = Depends(get_api_token),
    type_slug: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200)
):
    """
    Get public content items by content type slug.

    Requires a valid API token with read permission.
    """
    if not token.can_read:
        raise HTTPException(status_code=403, detail="Token does not have read permission")

    # Get content type
    content_type = db.query(ContentType).filter(
        and_(
            ContentType.slug == type_slug,
            ContentType.company_id == token.company_id
        )
    ).first()

    if not content_type:
        raise HTTPException(status_code=404, detail="Content type not found")

    # Build query
    query = db.query(ContentItem).filter(
        and_(
            ContentItem.content_type_id == content_type.id,
            ContentItem.company_id == token.company_id,
            ContentItem.visibility == ContentVisibility.PUBLIC.value,
            ContentItem.status == ContentStatus.PUBLISHED.value
        )
    )

    # Filter by knowledge base if token is scoped
    if token.knowledge_base_id:
        query = query.filter(ContentItem.knowledge_base_id == token.knowledge_base_id)

    total = query.count()
    items = query.order_by(ContentItem.created_at.desc()).offset(skip).limit(limit).all()

    response_items = [
        PublicContentItem(
            id=item.id,
            content_type_slug=content_type.slug,
            content_type_name=content_type.name,
            data=item.data,
            created_at=item.created_at,
            updated_at=item.updated_at
        )
        for item in items
    ]

    return PublicContentListResponse(items=response_items, total=total)


@router.get("/search", response_model=PublicSearchResponse)
def public_search(
    *,
    db: Session = Depends(get_db),
    token: ContentApiToken = Depends(get_api_token),
    q: str = Query(..., min_length=1, description="Search query"),
    content_type_slug: Optional[str] = Query(None, description="Filter by content type"),
    limit: int = Query(10, ge=1, le=100)
):
    """
    Search public content using semantic search.

    Requires a valid API token with search permission.
    Only searches content with 'public' visibility.
    """
    if not token.can_search:
        raise HTTPException(status_code=403, detail="Token does not have search permission")

    try:
        results = search_service.search_content(
            db=db,
            company_id=token.company_id,
            query=q,
            content_type_slug=content_type_slug,
            knowledge_base_id=token.knowledge_base_id,
            visibility_filter=[ContentVisibility.PUBLIC.value],
            limit=limit
        )

        return PublicSearchResponse(
            results=[PublicSearchResult(**r) for r in results],
            total=len(results),
            query=q
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/content-types", response_model=List[PublicContentTypeInfo])
def list_public_content_types(
    *,
    db: Session = Depends(get_db),
    token: ContentApiToken = Depends(get_api_token)
):
    """
    List content types that have public content.

    Requires a valid API token with read permission.
    """
    if not token.can_read:
        raise HTTPException(status_code=403, detail="Token does not have read permission")

    from sqlalchemy import func

    # Build base query
    query = db.query(
        ContentType.slug,
        ContentType.name,
        ContentType.description,
        ContentType.icon,
        func.count(ContentItem.id).label('item_count')
    ).join(ContentItem, ContentItem.content_type_id == ContentType.id).filter(
        and_(
            ContentItem.company_id == token.company_id,
            ContentItem.visibility == ContentVisibility.PUBLIC.value,
            ContentItem.status == ContentStatus.PUBLISHED.value
        )
    )

    # Filter by knowledge base if token is scoped
    if token.knowledge_base_id:
        query = query.filter(ContentItem.knowledge_base_id == token.knowledge_base_id)

    results = query.group_by(
        ContentType.slug,
        ContentType.name,
        ContentType.description,
        ContentType.icon
    ).all()

    return [
        PublicContentTypeInfo(
            slug=r.slug,
            name=r.name,
            description=r.description,
            icon=r.icon,
            item_count=r.item_count
        )
        for r in results
    ]


# ==================== Health Check ====================

@router.get("/health")
def public_api_health():
    """Health check endpoint for the public API."""
    return {"status": "ok", "api": "cms-public", "version": "1.0"}
