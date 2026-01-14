from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel, field_validator

from app.services.cms import tag_service
from app.core.dependencies import get_db, get_current_active_user
from app.models import user as models_user

router = APIRouter()


class TagCreate(BaseModel):
    name: str
    color: Optional[str] = None
    slug: Optional[str] = None

    @field_validator('color')
    @classmethod
    def validate_color(cls, v):
        if v is not None and v != "":
            import re
            if not re.match(r'^#[0-9A-Fa-f]{6}$', v):
                raise ValueError('Color must be in hex format (e.g., #FF5733)')
        return v


class TagUpdate(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None

    @field_validator('color')
    @classmethod
    def validate_color(cls, v):
        if v is not None and v != "":
            import re
            if not re.match(r'^#[0-9A-Fa-f]{6}$', v):
                raise ValueError('Color must be in hex format (e.g., #FF5733)')
        return v


class TagResponse(BaseModel):
    id: int
    company_id: int
    name: str
    slug: str
    color: Optional[str]
    usage_count: int

    class Config:
        from_attributes = True


class TagListResponse(BaseModel):
    items: List[TagResponse]
    total: int


class TagMergeRequest(BaseModel):
    source_tag_id: int
    target_tag_id: int


class BulkTagCreate(BaseModel):
    names: List[str]


@router.post("/", response_model=TagResponse)
def create_tag(
    *,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user),
    tag: TagCreate
):
    """Create a new tag."""
    try:
        db_tag = tag_service.create_tag(
            db=db,
            company_id=current_user.company_id,
            name=tag.name,
            color=tag.color,
            slug=tag.slug
        )
        return db_tag
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/bulk", response_model=List[TagResponse])
def create_or_get_tags(
    *,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user),
    bulk_create: BulkTagCreate
):
    """
    Create or get multiple tags by name.

    Returns existing tags if they already exist.
    """
    tags = tag_service.get_or_create_tags(
        db=db,
        company_id=current_user.company_id,
        tag_names=bulk_create.names
    )
    return tags


@router.get("/", response_model=TagListResponse)
def list_tags(
    *,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user),
    search: Optional[str] = Query(None, description="Search by tag name"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500)
):
    """
    List all tags for the company.

    Results are ordered by usage count (most used first).
    """
    tags = tag_service.get_tags(
        db=db,
        company_id=current_user.company_id,
        search=search,
        skip=skip,
        limit=limit
    )
    total = tag_service.get_tags_count(db, current_user.company_id, search)

    return TagListResponse(items=tags, total=total)


@router.get("/popular", response_model=List[TagResponse])
def get_popular_tags(
    *,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user),
    limit: int = Query(20, ge=1, le=100)
):
    """Get the most frequently used tags."""
    tags = tag_service.get_popular_tags(
        db=db,
        company_id=current_user.company_id,
        limit=limit
    )
    return tags


@router.get("/autocomplete", response_model=List[TagResponse])
def autocomplete_tags(
    *,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user),
    q: str = Query(..., min_length=1, description="Search query")
):
    """
    Autocomplete tags based on search query.

    Returns up to 10 matching tags.
    """
    tags = tag_service.get_tags(
        db=db,
        company_id=current_user.company_id,
        search=q,
        limit=10
    )
    return tags


@router.get("/{tag_id}", response_model=TagResponse)
def get_tag(
    *,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user),
    tag_id: int
):
    """Get a single tag by ID."""
    tag = tag_service.get_tag(db, tag_id, current_user.company_id)
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")
    return tag


@router.put("/{tag_id}", response_model=TagResponse)
def update_tag(
    *,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user),
    tag_id: int,
    tag_update: TagUpdate
):
    """Update a tag."""
    try:
        tag = tag_service.update_tag(
            db=db,
            tag_id=tag_id,
            company_id=current_user.company_id,
            name=tag_update.name,
            color=tag_update.color
        )
        if not tag:
            raise HTTPException(status_code=404, detail="Tag not found")
        return tag
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{tag_id}")
def delete_tag(
    *,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user),
    tag_id: int
):
    """Delete a tag."""
    deleted = tag_service.delete_tag(db, tag_id, current_user.company_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Tag not found")
    return {"message": "Tag deleted successfully"}


@router.post("/merge")
def merge_tags(
    *,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user),
    merge_request: TagMergeRequest
):
    """
    Merge one tag into another.

    The source tag will be deleted and its usage count added to the target.
    Content items should be updated separately to use the target tag.
    """
    try:
        target_tag = tag_service.merge_tags(
            db=db,
            source_tag_id=merge_request.source_tag_id,
            target_tag_id=merge_request.target_tag_id,
            company_id=current_user.company_id
        )
        if not target_tag:
            raise HTTPException(status_code=404, detail="One or both tags not found")
        return {
            "message": "Tags merged successfully",
            "target_tag": TagResponse.model_validate(target_tag)
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
