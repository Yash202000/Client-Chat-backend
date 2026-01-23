from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
import math

from app.schemas.cms import (
    ContentItemCreate,
    ContentItemUpdate,
    ContentItemResponse,
    ContentItemListResponse,
    ContentStatus,
    ContentVisibility,
    VisibilityUpdate
)
from app.services.cms import content_item_service, content_type_service
from app.core.dependencies import get_db, get_current_active_user
from app.models import user as models_user

router = APIRouter()


@router.post("/{type_slug}", response_model=ContentItemResponse)
def create_content_item(
    *,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user),
    type_slug: str,
    content_item: ContentItemCreate
):
    """
    Create a new content item for a given content type.

    The `data` field should contain values matching the content type's field schema.

    Example:
    ```json
    {
        "data": {
            "verse_text": "धर्मक्षेत्रे कुरुक्षेत्रे...",
            "meaning": "In the sacred field of Kurukshetra...",
            "audio": 45
        },
        "status": "draft",
        "visibility": "private",
        "category_ids": [1, 2]
    }
    ```
    """
    try:
        db_item = content_item_service.create_content_item_by_type_slug(
            db=db,
            type_slug=type_slug,
            content_item=content_item,
            company_id=current_user.company_id,
            user_id=current_user.id
        )
        return db_item
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{type_slug}", response_model=ContentItemListResponse)
def list_content_items(
    *,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user),
    type_slug: str,
    status: Optional[ContentStatus] = Query(None, description="Filter by status"),
    visibility: Optional[ContentVisibility] = Query(None, description="Filter by visibility"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page")
):
    """
    List content items for a given content type with pagination.
    """
    # Verify content type exists
    content_type = content_type_service.get_content_type_by_slug(
        db=db,
        slug=type_slug,
        company_id=current_user.company_id
    )
    if not content_type:
        raise HTTPException(status_code=404, detail="Content type not found")

    skip = (page - 1) * page_size
    items, total = content_item_service.get_content_items_by_type_slug(
        db=db,
        type_slug=type_slug,
        company_id=current_user.company_id,
        status=status,
        visibility=visibility,
        skip=skip,
        limit=page_size
    )

    return ContentItemListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        pages=math.ceil(total / page_size) if total > 0 else 0
    )


@router.get("/{type_slug}/{item_id}", response_model=ContentItemResponse)
def get_content_item(
    *,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user),
    type_slug: str,
    item_id: int
):
    """
    Get a single content item by ID.
    """
    # Verify content type exists
    content_type = content_type_service.get_content_type_by_slug(
        db=db,
        slug=type_slug,
        company_id=current_user.company_id
    )
    if not content_type:
        raise HTTPException(status_code=404, detail="Content type not found")

    item = content_item_service.get_content_item(
        db=db,
        item_id=item_id,
        company_id=current_user.company_id
    )
    if not item:
        raise HTTPException(status_code=404, detail="Content item not found")

    # Verify item belongs to the content type
    if item.content_type_id != content_type.id:
        raise HTTPException(status_code=404, detail="Content item not found in this content type")

    return item


@router.put("/{type_slug}/{item_id}", response_model=ContentItemResponse)
def update_content_item(
    *,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user),
    type_slug: str,
    item_id: int,
    content_item_update: ContentItemUpdate
):
    """
    Update a content item.

    Only fields provided in the request will be updated.
    The `data` field will be merged with existing data.
    """
    # Verify content type exists
    content_type = content_type_service.get_content_type_by_slug(
        db=db,
        slug=type_slug,
        company_id=current_user.company_id
    )
    if not content_type:
        raise HTTPException(status_code=404, detail="Content type not found")

    try:
        item = content_item_service.update_content_item(
            db=db,
            item_id=item_id,
            content_item_update=content_item_update,
            company_id=current_user.company_id,
            user_id=current_user.id
        )
        if not item:
            raise HTTPException(status_code=404, detail="Content item not found")

        # Verify item belongs to the content type
        if item.content_type_id != content_type.id:
            raise HTTPException(status_code=404, detail="Content item not found in this content type")

        return item
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{type_slug}/{item_id}")
def delete_content_item(
    *,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user),
    type_slug: str,
    item_id: int
):
    """
    Delete a content item.
    """
    # Verify content type exists
    content_type = content_type_service.get_content_type_by_slug(
        db=db,
        slug=type_slug,
        company_id=current_user.company_id
    )
    if not content_type:
        raise HTTPException(status_code=404, detail="Content type not found")

    # Verify item belongs to content type before deleting
    item = content_item_service.get_content_item(db, item_id, current_user.company_id)
    if not item:
        raise HTTPException(status_code=404, detail="Content item not found")
    if item.content_type_id != content_type.id:
        raise HTTPException(status_code=404, detail="Content item not found in this content type")

    deleted = content_item_service.delete_content_item(
        db=db,
        item_id=item_id,
        company_id=current_user.company_id
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Content item not found")

    return {"message": "Content item deleted successfully"}


@router.post("/{type_slug}/{item_id}/publish", response_model=ContentItemResponse)
def publish_content_item(
    *,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user),
    type_slug: str,
    item_id: int
):
    """
    Publish a content item (change status to 'published').
    """
    item = content_item_service.publish_content_item(
        db=db,
        item_id=item_id,
        company_id=current_user.company_id,
        user_id=current_user.id
    )
    if not item:
        raise HTTPException(status_code=404, detail="Content item not found")

    return item


@router.post("/{type_slug}/{item_id}/archive", response_model=ContentItemResponse)
def archive_content_item(
    *,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user),
    type_slug: str,
    item_id: int
):
    """
    Archive a content item (change status to 'archived').
    """
    item = content_item_service.archive_content_item(
        db=db,
        item_id=item_id,
        company_id=current_user.company_id,
        user_id=current_user.id
    )
    if not item:
        raise HTTPException(status_code=404, detail="Content item not found")

    return item


@router.post("/{type_slug}/{item_id}/visibility", response_model=ContentItemResponse)
def change_content_visibility(
    *,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user),
    type_slug: str,
    item_id: int,
    visibility_update: VisibilityUpdate
):
    """
    Change the visibility of a content item.

    Visibility levels:
    - `private`: Only creator can see
    - `company`: All users in company can see
    - `marketplace`: Listed in marketplace, others can copy
    - `public`: Accessible via public API
    """
    try:
        item = content_item_service.change_visibility(
            db=db,
            item_id=item_id,
            visibility=visibility_update.visibility,
            company_id=current_user.company_id,
            user_id=current_user.id
        )
        if not item:
            raise HTTPException(status_code=404, detail="Content item not found")

        return item
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
