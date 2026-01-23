from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel

from app.services.cms import search_service
from app.core.dependencies import get_db, get_current_active_user
from app.models import user as models_user

router = APIRouter()


class SearchResult(BaseModel):
    id: int
    content_type_slug: str
    data: dict
    score: float
    highlights: dict

    class Config:
        from_attributes = True


class SearchResponse(BaseModel):
    results: List[SearchResult]
    total: int
    query: str


class SemanticSearchRequest(BaseModel):
    query: str
    content_type_slug: Optional[str] = None
    knowledge_base_id: Optional[int] = None
    limit: int = 10


class ReindexResponse(BaseModel):
    success_count: int
    error_count: int
    message: str


@router.get("/", response_model=SearchResponse)
def quick_search(
    *,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user),
    q: str = Query(..., min_length=1, description="Search query"),
    content_type_slug: Optional[str] = Query(None, description="Filter by content type"),
    knowledge_base_id: Optional[int] = Query(None, description="Filter by knowledge base"),
    limit: int = Query(10, ge=1, le=100, description="Maximum results to return")
):
    """
    Quick semantic search for CMS content.

    Searches across all searchable fields in published content items.
    """
    try:
        results = search_service.search_content(
            db=db,
            company_id=current_user.company_id,
            query=q,
            content_type_slug=content_type_slug,
            knowledge_base_id=knowledge_base_id,
            limit=limit
        )

        return SearchResponse(
            results=[SearchResult(**r) for r in results],
            total=len(results),
            query=q
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/", response_model=SearchResponse)
def semantic_search(
    *,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user),
    search_request: SemanticSearchRequest
):
    """
    Perform semantic search on CMS content.

    Uses embeddings to find semantically similar content.
    """
    try:
        results = search_service.search_content(
            db=db,
            company_id=current_user.company_id,
            query=search_request.query,
            content_type_slug=search_request.content_type_slug,
            knowledge_base_id=search_request.knowledge_base_id,
            limit=search_request.limit
        )

        return SearchResponse(
            results=[SearchResult(**r) for r in results],
            total=len(results),
            query=search_request.query
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/marketplace", response_model=SearchResponse)
def search_marketplace(
    *,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user),
    q: str = Query(..., min_length=1, description="Search query"),
    content_type_slug: Optional[str] = Query(None, description="Filter by content type"),
    limit: int = Query(10, ge=1, le=100, description="Maximum results to return")
):
    """
    Search marketplace content across all companies.

    Only searches content with visibility='marketplace'.
    """
    try:
        results = search_service.search_marketplace(
            db=db,
            query=q,
            content_type_slug=content_type_slug,
            limit=limit
        )

        return SearchResponse(
            results=[SearchResult(**r) for r in results],
            total=len(results),
            query=q
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/reindex/content-type/{content_type_id}", response_model=ReindexResponse)
def reindex_content_type(
    *,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user),
    content_type_id: int
):
    """
    Reindex all content items of a specific content type.

    Use this after modifying which fields are searchable.
    """
    try:
        success_count, error_count = search_service.reindex_content_type(
            db=db,
            content_type_id=content_type_id,
            company_id=current_user.company_id
        )

        return ReindexResponse(
            success_count=success_count,
            error_count=error_count,
            message=f"Reindexed {success_count} items with {error_count} errors"
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/reindex/all", response_model=ReindexResponse)
def reindex_all_content(
    *,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user),
    knowledge_base_id: Optional[int] = Query(None, description="Only reindex specific knowledge base")
):
    """
    Reindex all published content for the company.

    This can be a long-running operation for large datasets.
    """
    try:
        success_count, error_count = search_service.reindex_all_content(
            db=db,
            company_id=current_user.company_id,
            knowledge_base_id=knowledge_base_id
        )

        return ReindexResponse(
            success_count=success_count,
            error_count=error_count,
            message=f"Reindexed {success_count} items with {error_count} errors"
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
