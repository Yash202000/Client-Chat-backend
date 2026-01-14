from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import and_
from app.models.content_category import ContentCategory
import re


def slugify(text: str) -> str:
    """Convert text to URL-friendly slug."""
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[-\s]+', '-', text)
    return text


def get_category(db: Session, category_id: int, company_id: int) -> Optional[ContentCategory]:
    """Get a category by ID."""
    return db.query(ContentCategory).filter(
        and_(
            ContentCategory.id == category_id,
            ContentCategory.company_id == company_id
        )
    ).first()


def get_category_by_slug(
    db: Session,
    slug: str,
    company_id: int,
    knowledge_base_id: Optional[int] = None
) -> Optional[ContentCategory]:
    """Get a category by slug."""
    query = db.query(ContentCategory).filter(
        and_(
            ContentCategory.slug == slug,
            ContentCategory.company_id == company_id
        )
    )
    if knowledge_base_id:
        query = query.filter(ContentCategory.knowledge_base_id == knowledge_base_id)
    return query.first()


def get_categories(
    db: Session,
    company_id: int,
    knowledge_base_id: Optional[int] = None,
    parent_id: Optional[int] = None,
    include_children: bool = False
) -> List[ContentCategory]:
    """
    Get categories with optional filters.
    If parent_id is None and include_children is False, returns root categories.
    """
    query = db.query(ContentCategory).filter(ContentCategory.company_id == company_id)

    if knowledge_base_id:
        query = query.filter(ContentCategory.knowledge_base_id == knowledge_base_id)

    if parent_id is not None:
        query = query.filter(ContentCategory.parent_id == parent_id)
    elif not include_children:
        # Get only root categories (no parent)
        query = query.filter(ContentCategory.parent_id.is_(None))

    return query.order_by(ContentCategory.display_order, ContentCategory.name).all()


def get_category_tree(
    db: Session,
    company_id: int,
    knowledge_base_id: Optional[int] = None
) -> List[Dict[str, Any]]:
    """
    Get categories as a hierarchical tree structure.
    Returns nested dictionaries with children.
    """
    # Get all categories for the company/knowledge base
    query = db.query(ContentCategory).filter(ContentCategory.company_id == company_id)
    if knowledge_base_id:
        query = query.filter(ContentCategory.knowledge_base_id == knowledge_base_id)

    all_categories = query.order_by(ContentCategory.display_order, ContentCategory.name).all()

    # Build tree structure
    category_map = {}
    root_categories = []

    # First pass: create dict for each category
    for cat in all_categories:
        category_map[cat.id] = {
            "id": cat.id,
            "name": cat.name,
            "slug": cat.slug,
            "description": cat.description,
            "icon": cat.icon,
            "parent_id": cat.parent_id,
            "display_order": cat.display_order,
            "children": []
        }

    # Second pass: build tree
    for cat in all_categories:
        cat_dict = category_map[cat.id]
        if cat.parent_id and cat.parent_id in category_map:
            category_map[cat.parent_id]["children"].append(cat_dict)
        else:
            root_categories.append(cat_dict)

    return root_categories


def create_category(
    db: Session,
    company_id: int,
    name: str,
    knowledge_base_id: Optional[int] = None,
    parent_id: Optional[int] = None,
    description: Optional[str] = None,
    icon: Optional[str] = None,
    slug: Optional[str] = None,
    display_order: int = 0
) -> ContentCategory:
    """Create a new category."""
    # Generate slug if not provided
    if not slug:
        slug = slugify(name)

    # Ensure unique slug within company/knowledge_base
    base_slug = slug
    counter = 1
    while get_category_by_slug(db, slug, company_id, knowledge_base_id):
        slug = f"{base_slug}-{counter}"
        counter += 1

    # Validate parent exists if provided
    if parent_id:
        parent = get_category(db, parent_id, company_id)
        if not parent:
            raise ValueError("Parent category not found")
        # Ensure parent is in same knowledge base
        if knowledge_base_id and parent.knowledge_base_id != knowledge_base_id:
            raise ValueError("Parent category must be in the same knowledge base")

    db_category = ContentCategory(
        company_id=company_id,
        knowledge_base_id=knowledge_base_id,
        parent_id=parent_id,
        name=name,
        slug=slug,
        description=description,
        icon=icon,
        display_order=display_order
    )

    db.add(db_category)
    db.commit()
    db.refresh(db_category)

    return db_category


def update_category(
    db: Session,
    category_id: int,
    company_id: int,
    name: Optional[str] = None,
    description: Optional[str] = None,
    icon: Optional[str] = None,
    parent_id: Optional[int] = None,
    display_order: Optional[int] = None
) -> Optional[ContentCategory]:
    """Update an existing category."""
    db_category = get_category(db, category_id, company_id)
    if not db_category:
        return None

    if name is not None:
        db_category.name = name
        # Update slug if name changes
        new_slug = slugify(name)
        if new_slug != db_category.slug:
            base_slug = new_slug
            counter = 1
            while True:
                existing = get_category_by_slug(
                    db, new_slug, company_id, db_category.knowledge_base_id
                )
                if not existing or existing.id == category_id:
                    break
                new_slug = f"{base_slug}-{counter}"
                counter += 1
            db_category.slug = new_slug

    if description is not None:
        db_category.description = description

    if icon is not None:
        db_category.icon = icon

    if display_order is not None:
        db_category.display_order = display_order

    # Handle parent change
    if parent_id is not None:
        if parent_id == 0:
            # Set to root category
            db_category.parent_id = None
        else:
            # Validate parent exists and isn't a descendant
            parent = get_category(db, parent_id, company_id)
            if not parent:
                raise ValueError("Parent category not found")
            if parent_id == category_id:
                raise ValueError("Category cannot be its own parent")
            # Check for circular reference
            if _is_descendant(db, parent_id, category_id, company_id):
                raise ValueError("Cannot set parent to a descendant category")
            db_category.parent_id = parent_id

    db.commit()
    db.refresh(db_category)

    return db_category


def _is_descendant(db: Session, category_id: int, potential_ancestor_id: int, company_id: int) -> bool:
    """Check if category_id is a descendant of potential_ancestor_id."""
    children = db.query(ContentCategory).filter(
        and_(
            ContentCategory.parent_id == potential_ancestor_id,
            ContentCategory.company_id == company_id
        )
    ).all()

    for child in children:
        if child.id == category_id:
            return True
        if _is_descendant(db, category_id, child.id, company_id):
            return True

    return False


def delete_category(
    db: Session,
    category_id: int,
    company_id: int,
    delete_children: bool = False
) -> bool:
    """
    Delete a category.
    If delete_children is True, all child categories are also deleted.
    If False and category has children, deletion fails.
    """
    db_category = get_category(db, category_id, company_id)
    if not db_category:
        return False

    # Check for children
    children = db.query(ContentCategory).filter(
        ContentCategory.parent_id == category_id
    ).all()

    if children:
        if delete_children:
            # Recursively delete children
            for child in children:
                delete_category(db, child.id, company_id, delete_children=True)
        else:
            raise ValueError("Category has children. Set delete_children=True to delete all.")

    db.delete(db_category)
    db.commit()

    return True


def move_category(
    db: Session,
    category_id: int,
    new_parent_id: Optional[int],
    company_id: int
) -> Optional[ContentCategory]:
    """Move a category to a new parent (or to root if new_parent_id is None)."""
    return update_category(
        db=db,
        category_id=category_id,
        company_id=company_id,
        parent_id=new_parent_id if new_parent_id else 0
    )


def reorder_categories(
    db: Session,
    category_orders: List[Dict[str, int]],
    company_id: int
) -> bool:
    """
    Update display order for multiple categories at once.
    category_orders: [{"id": 1, "display_order": 0}, {"id": 2, "display_order": 1}, ...]
    """
    for order in category_orders:
        cat_id = order.get("id")
        display_order = order.get("display_order")
        if cat_id is not None and display_order is not None:
            db_category = get_category(db, cat_id, company_id)
            if db_category:
                db_category.display_order = display_order

    db.commit()
    return True


def get_category_path(db: Session, category_id: int, company_id: int) -> List[Dict[str, Any]]:
    """Get the full path from root to this category (breadcrumb)."""
    path = []
    current = get_category(db, category_id, company_id)

    while current:
        path.insert(0, {
            "id": current.id,
            "name": current.name,
            "slug": current.slug
        })
        if current.parent_id:
            current = get_category(db, current.parent_id, company_id)
        else:
            break

    return path
