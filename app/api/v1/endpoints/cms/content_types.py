from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional

from app.schemas.cms import (
    ContentTypeCreate,
    ContentTypeUpdate,
    ContentTypeResponse,
    FieldDefinition
)
from app.services.cms import content_type_service
from app.core.dependencies import get_db, get_current_active_user
from app.models import user as models_user

router = APIRouter()


@router.post("/", response_model=ContentTypeResponse)
def create_content_type(
    *,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user),
    content_type: ContentTypeCreate
):
    """
    Create a new content type with a field schema.

    Example field_schema:
    ```json
    [
        {"slug": "title", "name": "Title", "type": "text", "required": true, "searchable": true},
        {"slug": "content", "name": "Content", "type": "rich_text", "searchable": true},
        {"slug": "image", "name": "Featured Image", "type": "media"}
    ]
    ```
    """
    try:
        db_content_type = content_type_service.create_content_type(
            db=db,
            content_type=content_type,
            company_id=current_user.company_id
        )
        return db_content_type
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/", response_model=List[ContentTypeResponse])
def list_content_types(
    *,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user),
    knowledge_base_id: Optional[int] = Query(None, description="Filter by knowledge base"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500)
):
    """
    List all content types for the current company.
    Optionally filter by knowledge base.
    """
    content_types = content_type_service.get_content_types(
        db=db,
        company_id=current_user.company_id,
        knowledge_base_id=knowledge_base_id,
        skip=skip,
        limit=limit
    )
    return content_types


@router.get("/{slug}", response_model=ContentTypeResponse)
def get_content_type(
    *,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user),
    slug: str
):
    """
    Get a content type by its slug.
    """
    content_type = content_type_service.get_content_type_by_slug(
        db=db,
        slug=slug,
        company_id=current_user.company_id
    )
    if not content_type:
        raise HTTPException(status_code=404, detail="Content type not found")
    return content_type


@router.put("/{slug}", response_model=ContentTypeResponse)
def update_content_type(
    *,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user),
    slug: str,
    content_type_update: ContentTypeUpdate
):
    """
    Update a content type by its slug.
    """
    try:
        content_type = content_type_service.update_content_type_by_slug(
            db=db,
            slug=slug,
            content_type_update=content_type_update,
            company_id=current_user.company_id
        )
        if not content_type:
            raise HTTPException(status_code=404, detail="Content type not found")
        return content_type
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{slug}")
def delete_content_type(
    *,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user),
    slug: str
):
    """
    Delete a content type and all its content items.
    """
    deleted = content_type_service.delete_content_type_by_slug(
        db=db,
        slug=slug,
        company_id=current_user.company_id
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Content type not found")
    return {"message": "Content type deleted successfully"}


@router.post("/{slug}/fields", response_model=ContentTypeResponse)
def add_field_to_content_type(
    *,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user),
    slug: str,
    field: FieldDefinition
):
    """
    Add a new field to an existing content type's schema.
    """
    content_type = content_type_service.get_content_type_by_slug(
        db=db,
        slug=slug,
        company_id=current_user.company_id
    )
    if not content_type:
        raise HTTPException(status_code=404, detail="Content type not found")

    try:
        updated = content_type_service.add_field_to_schema(
            db=db,
            content_type_id=content_type.id,
            field=field,
            company_id=current_user.company_id
        )
        return updated
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{slug}/fields/{field_slug}", response_model=ContentTypeResponse)
def remove_field_from_content_type(
    *,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user),
    slug: str,
    field_slug: str
):
    """
    Remove a field from an existing content type's schema.
    Note: This does not remove data from existing content items.
    """
    content_type = content_type_service.get_content_type_by_slug(
        db=db,
        slug=slug,
        company_id=current_user.company_id
    )
    if not content_type:
        raise HTTPException(status_code=404, detail="Content type not found")

    try:
        updated = content_type_service.remove_field_from_schema(
            db=db,
            content_type_id=content_type.id,
            field_slug=field_slug,
            company_id=current_user.company_id
        )
        return updated
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
