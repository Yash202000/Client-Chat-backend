from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel

from app.services.cms import category_service
from app.core.dependencies import get_db, get_current_active_user
from app.models import user as models_user

router = APIRouter()


class CategoryBase(BaseModel):
    name: str
    description: Optional[str] = None
    icon: Optional[str] = None
    parent_id: Optional[int] = None
    display_order: int = 0


class CategoryCreate(CategoryBase):
    knowledge_base_id: Optional[int] = None
    slug: Optional[str] = None


class CategoryUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    icon: Optional[str] = None
    parent_id: Optional[int] = None
    display_order: Optional[int] = None


class CategoryResponse(BaseModel):
    id: int
    company_id: int
    knowledge_base_id: Optional[int]
    parent_id: Optional[int]
    name: str
    slug: str
    description: Optional[str]
    icon: Optional[str]
    display_order: int

    class Config:
        from_attributes = True


class CategoryTreeNode(BaseModel):
    id: int
    name: str
    slug: str
    description: Optional[str]
    icon: Optional[str]
    parent_id: Optional[int]
    display_order: int
    children: List['CategoryTreeNode'] = []


class CategoryPath(BaseModel):
    id: int
    name: str
    slug: str


class CategoryOrderItem(BaseModel):
    id: int
    display_order: int


class CategoryReorderRequest(BaseModel):
    orders: List[CategoryOrderItem]


@router.post("/", response_model=CategoryResponse)
def create_category(
    *,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user),
    category: CategoryCreate
):
    """Create a new category."""
    try:
        db_category = category_service.create_category(
            db=db,
            company_id=current_user.company_id,
            name=category.name,
            knowledge_base_id=category.knowledge_base_id,
            parent_id=category.parent_id,
            description=category.description,
            icon=category.icon,
            slug=category.slug,
            display_order=category.display_order
        )
        return db_category
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/", response_model=List[CategoryResponse])
def list_categories(
    *,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user),
    knowledge_base_id: Optional[int] = Query(None, description="Filter by knowledge base"),
    parent_id: Optional[int] = Query(None, description="Filter by parent category"),
    include_all: bool = Query(False, description="Include all categories (not just root)")
):
    """
    List categories.

    By default, returns only root categories (no parent).
    Use parent_id to get children of a specific category.
    Use include_all=true to get all categories flat.
    """
    categories = category_service.get_categories(
        db=db,
        company_id=current_user.company_id,
        knowledge_base_id=knowledge_base_id,
        parent_id=parent_id,
        include_children=include_all
    )
    return categories


@router.get("/tree", response_model=List[CategoryTreeNode])
def get_category_tree(
    *,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user),
    knowledge_base_id: Optional[int] = Query(None, description="Filter by knowledge base")
):
    """
    Get categories as a hierarchical tree structure.

    Returns nested categories with their children.
    """
    tree = category_service.get_category_tree(
        db=db,
        company_id=current_user.company_id,
        knowledge_base_id=knowledge_base_id
    )
    return tree


@router.get("/{category_id}", response_model=CategoryResponse)
def get_category(
    *,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user),
    category_id: int
):
    """Get a single category by ID."""
    category = category_service.get_category(db, category_id, current_user.company_id)
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")
    return category


@router.get("/{category_id}/path", response_model=List[CategoryPath])
def get_category_path(
    *,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user),
    category_id: int
):
    """
    Get the full path from root to this category (breadcrumb).

    Returns a list of categories from root to the specified category.
    """
    path = category_service.get_category_path(
        db=db,
        category_id=category_id,
        company_id=current_user.company_id
    )
    if not path:
        raise HTTPException(status_code=404, detail="Category not found")
    return path


@router.get("/{category_id}/children", response_model=List[CategoryResponse])
def get_category_children(
    *,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user),
    category_id: int
):
    """Get direct children of a category."""
    # Verify parent exists
    parent = category_service.get_category(db, category_id, current_user.company_id)
    if not parent:
        raise HTTPException(status_code=404, detail="Category not found")

    children = category_service.get_categories(
        db=db,
        company_id=current_user.company_id,
        parent_id=category_id
    )
    return children


@router.put("/{category_id}", response_model=CategoryResponse)
def update_category(
    *,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user),
    category_id: int,
    category_update: CategoryUpdate
):
    """Update a category."""
    try:
        category = category_service.update_category(
            db=db,
            category_id=category_id,
            company_id=current_user.company_id,
            name=category_update.name,
            description=category_update.description,
            icon=category_update.icon,
            parent_id=category_update.parent_id,
            display_order=category_update.display_order
        )
        if not category:
            raise HTTPException(status_code=404, detail="Category not found")
        return category
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{category_id}")
def delete_category(
    *,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user),
    category_id: int,
    delete_children: bool = Query(False, description="Also delete child categories")
):
    """
    Delete a category.

    If the category has children and delete_children is False, deletion will fail.
    Set delete_children=True to delete all nested categories.
    """
    try:
        deleted = category_service.delete_category(
            db=db,
            category_id=category_id,
            company_id=current_user.company_id,
            delete_children=delete_children
        )
        if not deleted:
            raise HTTPException(status_code=404, detail="Category not found")
        return {"message": "Category deleted successfully"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{category_id}/move")
def move_category(
    *,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user),
    category_id: int,
    new_parent_id: Optional[int] = Query(None, description="New parent ID (null for root)")
):
    """
    Move a category to a new parent.

    Set new_parent_id to null to move to root level.
    """
    try:
        category = category_service.move_category(
            db=db,
            category_id=category_id,
            new_parent_id=new_parent_id,
            company_id=current_user.company_id
        )
        if not category:
            raise HTTPException(status_code=404, detail="Category not found")
        return {"message": "Category moved successfully", "category_id": category.id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/reorder")
def reorder_categories(
    *,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user),
    reorder_request: CategoryReorderRequest
):
    """
    Update display order for multiple categories at once.

    Useful for drag-and-drop reordering in the UI.
    """
    category_service.reorder_categories(
        db=db,
        category_orders=[{"id": o.id, "display_order": o.display_order} for o in reorder_request.orders],
        company_id=current_user.company_id
    )
    return {"message": "Categories reordered successfully"}
