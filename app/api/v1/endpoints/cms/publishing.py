from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime

from app.services.cms import publishing_service, export_service
from app.core.dependencies import get_db, get_current_active_user
from app.models import user as models_user
from app.schemas.cms import ContentItemResponse

router = APIRouter()


# ==================== Marketplace ====================

class MarketplaceItemResponse(BaseModel):
    id: int
    content_type_slug: str
    content_type_name: str
    data: dict
    is_featured: bool
    download_count: int
    company_name: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class MarketplaceListResponse(BaseModel):
    items: List[MarketplaceItemResponse]
    total: int


class ContentTypeCount(BaseModel):
    slug: str
    name: str
    icon: Optional[str]
    item_count: int


class CopyFromMarketplaceRequest(BaseModel):
    original_item_id: int
    knowledge_base_id: Optional[int] = None


@router.get("/marketplace", response_model=MarketplaceListResponse)
def browse_marketplace(
    *,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user),
    content_type_slug: Optional[str] = Query(None, description="Filter by content type"),
    search: Optional[str] = Query(None, description="Search in content"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200)
):
    """
    Browse marketplace content.

    Returns published items with marketplace visibility from all companies.
    """
    items, total = publishing_service.get_marketplace_items(
        db=db,
        content_type_slug=content_type_slug,
        search=search,
        skip=skip,
        limit=limit
    )

    response_items = []
    for item in items:
        response_items.append(MarketplaceItemResponse(
            id=item.id,
            content_type_slug=item.content_type.slug if item.content_type else "",
            content_type_name=item.content_type.name if item.content_type else "",
            data=item.data,
            is_featured=item.is_featured,
            download_count=item.download_count,
            company_name=item.company.name if item.company else None,
            created_at=item.created_at
        ))

    return MarketplaceListResponse(items=response_items, total=total)


@router.get("/marketplace/featured", response_model=List[MarketplaceItemResponse])
def get_featured_marketplace(
    *,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user),
    limit: int = Query(10, ge=1, le=50)
):
    """Get featured marketplace items."""
    items = publishing_service.get_featured_marketplace_items(db, limit)

    return [
        MarketplaceItemResponse(
            id=item.id,
            content_type_slug=item.content_type.slug if item.content_type else "",
            content_type_name=item.content_type.name if item.content_type else "",
            data=item.data,
            is_featured=item.is_featured,
            download_count=item.download_count,
            company_name=item.company.name if item.company else None,
            created_at=item.created_at
        )
        for item in items
    ]


@router.get("/marketplace/content-types", response_model=List[ContentTypeCount])
def get_marketplace_content_types(
    *,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """Get content types that have items in the marketplace."""
    return publishing_service.get_marketplace_content_types(db)


@router.post("/marketplace/copy", response_model=ContentItemResponse)
def copy_from_marketplace(
    *,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user),
    copy_request: CopyFromMarketplaceRequest
):
    """
    Copy a marketplace item to your own content.

    Creates a new content item with status='draft' and visibility='private'.
    The content type will be created if it doesn't exist in your company.
    """
    try:
        copied_item = publishing_service.copy_from_marketplace(
            db=db,
            original_item_id=copy_request.original_item_id,
            target_company_id=current_user.company_id,
            target_user_id=current_user.id,
            target_knowledge_base_id=copy_request.knowledge_base_id
        )
        return copied_item
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/items/{item_id}/feature")
def set_item_featured(
    *,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user),
    item_id: int,
    is_featured: bool = Query(..., description="Set featured status")
):
    """Set or unset an item as featured in the marketplace."""
    try:
        item = publishing_service.set_featured(
            db=db,
            item_id=item_id,
            company_id=current_user.company_id,
            is_featured=is_featured
        )
        if not item:
            raise HTTPException(status_code=404, detail="Item not found")
        return {"message": f"Item {'featured' if is_featured else 'unfeatured'} successfully"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ==================== API Tokens ====================

class ApiTokenCreate(BaseModel):
    name: str
    knowledge_base_id: Optional[int] = None
    can_read: bool = True
    can_search: bool = True
    rate_limit: int = 100
    expires_at: Optional[datetime] = None


class ApiTokenUpdate(BaseModel):
    name: Optional[str] = None
    can_read: Optional[bool] = None
    can_search: Optional[bool] = None
    rate_limit: Optional[int] = None
    is_active: Optional[bool] = None
    expires_at: Optional[datetime] = None


class ApiTokenResponse(BaseModel):
    id: int
    company_id: int
    knowledge_base_id: Optional[int]
    token: str
    name: Optional[str]
    can_read: bool
    can_search: bool
    rate_limit: int
    last_used_at: Optional[datetime]
    request_count: int
    is_active: bool
    expires_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True


class ApiTokenListResponse(BaseModel):
    token: str  # Only shown on creation
    id: int
    name: Optional[str]
    can_read: bool
    can_search: bool
    rate_limit: int
    is_active: bool
    expires_at: Optional[datetime]
    request_count: int
    last_used_at: Optional[datetime]
    created_at: datetime


@router.post("/api-tokens", response_model=ApiTokenResponse)
def create_api_token(
    *,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user),
    token_data: ApiTokenCreate
):
    """
    Create a new API token for public content access.

    **Important:** The token value is only returned once on creation.
    Store it securely as it cannot be retrieved again.
    """
    token = publishing_service.create_api_token(
        db=db,
        company_id=current_user.company_id,
        name=token_data.name,
        knowledge_base_id=token_data.knowledge_base_id,
        can_read=token_data.can_read,
        can_search=token_data.can_search,
        rate_limit=token_data.rate_limit,
        expires_at=token_data.expires_at
    )
    return token


@router.get("/api-tokens", response_model=List[ApiTokenListResponse])
def list_api_tokens(
    *,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user),
    knowledge_base_id: Optional[int] = Query(None, description="Filter by knowledge base")
):
    """List all API tokens for the company."""
    tokens = publishing_service.get_api_tokens(
        db=db,
        company_id=current_user.company_id,
        knowledge_base_id=knowledge_base_id
    )

    # Mask token values in list (only show first/last 4 chars)
    return [
        ApiTokenListResponse(
            id=t.id,
            token=f"{t.token[:4]}...{t.token[-4:]}",
            name=t.name,
            can_read=t.can_read,
            can_search=t.can_search,
            rate_limit=t.rate_limit,
            is_active=t.is_active,
            expires_at=t.expires_at,
            request_count=t.request_count,
            last_used_at=t.last_used_at,
            created_at=t.created_at
        )
        for t in tokens
    ]


@router.put("/api-tokens/{token_id}", response_model=ApiTokenListResponse)
def update_api_token(
    *,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user),
    token_id: int,
    token_update: ApiTokenUpdate
):
    """Update an API token's settings."""
    token = publishing_service.update_api_token(
        db=db,
        token_id=token_id,
        company_id=current_user.company_id,
        name=token_update.name,
        can_read=token_update.can_read,
        can_search=token_update.can_search,
        rate_limit=token_update.rate_limit,
        is_active=token_update.is_active,
        expires_at=token_update.expires_at
    )
    if not token:
        raise HTTPException(status_code=404, detail="API token not found")

    return ApiTokenListResponse(
        id=token.id,
        token=f"{token.token[:4]}...{token.token[-4:]}",
        name=token.name,
        can_read=token.can_read,
        can_search=token.can_search,
        rate_limit=token.rate_limit,
        is_active=token.is_active,
        expires_at=token.expires_at,
        request_count=token.request_count,
        last_used_at=token.last_used_at,
        created_at=token.created_at
    )


@router.delete("/api-tokens/{token_id}")
def delete_api_token(
    *,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user),
    token_id: int
):
    """Revoke (delete) an API token."""
    deleted = publishing_service.delete_api_token(db, token_id, current_user.company_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="API token not found")
    return {"message": "API token revoked successfully"}


@router.post("/api-tokens/{token_id}/regenerate", response_model=ApiTokenResponse)
def regenerate_api_token(
    *,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user),
    token_id: int
):
    """
    Regenerate the token string for an API token.

    **Important:** The old token will immediately stop working.
    The new token is only returned once - store it securely.
    """
    token = publishing_service.regenerate_api_token(db, token_id, current_user.company_id)
    if not token:
        raise HTTPException(status_code=404, detail="API token not found")
    return token


# ==================== Exports ====================

class ExportRequest(BaseModel):
    format: str  # json or csv
    knowledge_base_id: Optional[int] = None
    content_type_id: Optional[int] = None
    status: Optional[str] = None
    visibility: Optional[str] = None


class ExportResponse(BaseModel):
    id: int
    company_id: int
    knowledge_base_id: Optional[int]
    format: str
    status: str
    file_size: Optional[int]
    item_count: Optional[int]
    completed_at: Optional[datetime]
    expires_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True


class ExportDownloadResponse(BaseModel):
    download_url: str
    expires_in: int


@router.post("/exports", response_model=ExportResponse)
def create_export(
    *,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user),
    background_tasks: BackgroundTasks,
    export_request: ExportRequest
):
    """
    Request a content export.

    The export is processed in the background. Check the status
    using GET /exports/{id} and download when completed.
    """
    try:
        export_record = export_service.create_export_request(
            db=db,
            company_id=current_user.company_id,
            user_id=current_user.id,
            export_format=export_request.format,
            knowledge_base_id=export_request.knowledge_base_id,
            content_type_id=export_request.content_type_id,
            status_filter=export_request.status,
            visibility_filter=export_request.visibility
        )

        # Process in background
        background_tasks.add_task(
            export_service.process_export,
            db, export_record.id, current_user.company_id
        )

        return export_record
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/exports", response_model=List[ExportResponse])
def list_exports(
    *,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100)
):
    """List export history."""
    exports = export_service.get_exports(
        db=db,
        company_id=current_user.company_id,
        skip=skip,
        limit=limit
    )
    return exports


@router.get("/exports/{export_id}", response_model=ExportResponse)
def get_export(
    *,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user),
    export_id: int
):
    """Get export status and details."""
    export_record = export_service.get_export(db, export_id, current_user.company_id)
    if not export_record:
        raise HTTPException(status_code=404, detail="Export not found")
    return export_record


@router.get("/exports/{export_id}/download", response_model=ExportDownloadResponse)
def download_export(
    *,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user),
    export_id: int,
    expires_in: int = Query(3600, ge=60, le=86400, description="URL expiration in seconds")
):
    """Get a download URL for a completed export."""
    export_record = export_service.get_export(db, export_id, current_user.company_id)
    if not export_record:
        raise HTTPException(status_code=404, detail="Export not found")

    if export_record.status != 'completed':
        raise HTTPException(status_code=400, detail=f"Export is {export_record.status}, not ready for download")

    url = export_service.get_export_download_url(db, export_id, current_user.company_id, expires_in)
    if not url:
        raise HTTPException(status_code=500, detail="Failed to generate download URL")

    return ExportDownloadResponse(download_url=url, expires_in=expires_in)


@router.delete("/exports/{export_id}")
def delete_export(
    *,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user),
    export_id: int
):
    """Delete an export and its file."""
    deleted = export_service.delete_export(db, export_id, current_user.company_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Export not found")
    return {"message": "Export deleted successfully"}


@router.post("/exports/immediate")
def export_immediate(
    *,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user),
    export_request: ExportRequest
):
    """
    Export content immediately and return the data directly.

    Use this for smaller exports. For large datasets, use POST /exports instead.
    """
    try:
        result = export_service.export_content_immediate(
            db=db,
            company_id=current_user.company_id,
            user_id=current_user.id,
            export_format=export_request.format,
            knowledge_base_id=export_request.knowledge_base_id,
            content_type_id=export_request.content_type_id,
            status_filter=export_request.status
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
