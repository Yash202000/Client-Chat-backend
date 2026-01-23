from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_, func
from app.models.content_tag import ContentTag
import re


def slugify(text: str) -> str:
    """Convert text to URL-friendly slug."""
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[-\s]+', '-', text)
    return text


def get_tag(db: Session, tag_id: int, company_id: int) -> Optional[ContentTag]:
    """Get a tag by ID."""
    return db.query(ContentTag).filter(
        and_(
            ContentTag.id == tag_id,
            ContentTag.company_id == company_id
        )
    ).first()


def get_tag_by_slug(db: Session, slug: str, company_id: int) -> Optional[ContentTag]:
    """Get a tag by slug."""
    return db.query(ContentTag).filter(
        and_(
            ContentTag.slug == slug,
            ContentTag.company_id == company_id
        )
    ).first()


def get_tag_by_name(db: Session, name: str, company_id: int) -> Optional[ContentTag]:
    """Get a tag by name (case-insensitive)."""
    return db.query(ContentTag).filter(
        and_(
            func.lower(ContentTag.name) == name.lower(),
            ContentTag.company_id == company_id
        )
    ).first()


def get_tags(
    db: Session,
    company_id: int,
    search: Optional[str] = None,
    skip: int = 0,
    limit: int = 100
) -> List[ContentTag]:
    """Get tags with optional search filter."""
    query = db.query(ContentTag).filter(ContentTag.company_id == company_id)

    if search:
        query = query.filter(ContentTag.name.ilike(f'%{search}%'))

    return query.order_by(ContentTag.usage_count.desc(), ContentTag.name).offset(skip).limit(limit).all()


def get_tags_count(db: Session, company_id: int, search: Optional[str] = None) -> int:
    """Get count of tags."""
    query = db.query(ContentTag).filter(ContentTag.company_id == company_id)
    if search:
        query = query.filter(ContentTag.name.ilike(f'%{search}%'))
    return query.count()


def get_popular_tags(db: Session, company_id: int, limit: int = 20) -> List[ContentTag]:
    """Get most used tags."""
    return db.query(ContentTag).filter(
        and_(
            ContentTag.company_id == company_id,
            ContentTag.usage_count > 0
        )
    ).order_by(ContentTag.usage_count.desc()).limit(limit).all()


def create_tag(
    db: Session,
    company_id: int,
    name: str,
    color: Optional[str] = None,
    slug: Optional[str] = None
) -> ContentTag:
    """Create a new tag."""
    # Check if tag with same name exists
    existing = get_tag_by_name(db, name, company_id)
    if existing:
        raise ValueError(f"Tag '{name}' already exists")

    # Generate slug if not provided
    if not slug:
        slug = slugify(name)

    # Ensure unique slug
    base_slug = slug
    counter = 1
    while get_tag_by_slug(db, slug, company_id):
        slug = f"{base_slug}-{counter}"
        counter += 1

    # Validate color format if provided
    if color and not re.match(r'^#[0-9A-Fa-f]{6}$', color):
        raise ValueError("Color must be in hex format (e.g., #FF5733)")

    db_tag = ContentTag(
        company_id=company_id,
        name=name,
        slug=slug,
        color=color
    )

    db.add(db_tag)
    db.commit()
    db.refresh(db_tag)

    return db_tag


def update_tag(
    db: Session,
    tag_id: int,
    company_id: int,
    name: Optional[str] = None,
    color: Optional[str] = None
) -> Optional[ContentTag]:
    """Update an existing tag."""
    db_tag = get_tag(db, tag_id, company_id)
    if not db_tag:
        return None

    if name is not None:
        # Check if new name conflicts with existing tag
        existing = get_tag_by_name(db, name, company_id)
        if existing and existing.id != tag_id:
            raise ValueError(f"Tag '{name}' already exists")
        db_tag.name = name
        # Update slug
        new_slug = slugify(name)
        base_slug = new_slug
        counter = 1
        while True:
            existing_slug = get_tag_by_slug(db, new_slug, company_id)
            if not existing_slug or existing_slug.id == tag_id:
                break
            new_slug = f"{base_slug}-{counter}"
            counter += 1
        db_tag.slug = new_slug

    if color is not None:
        if color == "":
            db_tag.color = None
        elif not re.match(r'^#[0-9A-Fa-f]{6}$', color):
            raise ValueError("Color must be in hex format (e.g., #FF5733)")
        else:
            db_tag.color = color

    db.commit()
    db.refresh(db_tag)

    return db_tag


def delete_tag(db: Session, tag_id: int, company_id: int) -> bool:
    """Delete a tag."""
    db_tag = get_tag(db, tag_id, company_id)
    if not db_tag:
        return False

    db.delete(db_tag)
    db.commit()

    return True


def get_or_create_tag(
    db: Session,
    company_id: int,
    name: str,
    color: Optional[str] = None
) -> ContentTag:
    """Get existing tag by name or create a new one."""
    existing = get_tag_by_name(db, name, company_id)
    if existing:
        return existing
    return create_tag(db, company_id, name, color)


def get_or_create_tags(
    db: Session,
    company_id: int,
    tag_names: List[str]
) -> List[ContentTag]:
    """Get or create multiple tags by name."""
    tags = []
    for name in tag_names:
        name = name.strip()
        if name:
            tag = get_or_create_tag(db, company_id, name)
            tags.append(tag)
    return tags


def increment_usage_count(db: Session, tag_id: int, company_id: int) -> None:
    """Increment the usage count for a tag."""
    db_tag = get_tag(db, tag_id, company_id)
    if db_tag:
        db_tag.usage_count += 1
        db.commit()


def decrement_usage_count(db: Session, tag_id: int, company_id: int) -> None:
    """Decrement the usage count for a tag."""
    db_tag = get_tag(db, tag_id, company_id)
    if db_tag and db_tag.usage_count > 0:
        db_tag.usage_count -= 1
        db.commit()


def merge_tags(
    db: Session,
    source_tag_id: int,
    target_tag_id: int,
    company_id: int
) -> Optional[ContentTag]:
    """
    Merge source tag into target tag.
    All content with source tag will be updated to use target tag.
    Source tag is deleted after merge.
    """
    source_tag = get_tag(db, source_tag_id, company_id)
    target_tag = get_tag(db, target_tag_id, company_id)

    if not source_tag or not target_tag:
        return None

    if source_tag_id == target_tag_id:
        raise ValueError("Cannot merge a tag into itself")

    # Update usage count
    target_tag.usage_count += source_tag.usage_count

    # Delete source tag
    db.delete(source_tag)
    db.commit()
    db.refresh(target_tag)

    return target_tag
