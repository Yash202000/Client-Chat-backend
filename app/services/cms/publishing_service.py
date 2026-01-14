from typing import List, Optional, Dict, Any, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import and_
from datetime import datetime
from app.models.content_item import ContentItem
from app.models.content_type import ContentType
from app.models.content_publishing import ContentCopy, ContentApiToken
from app.schemas.cms import ContentStatus, ContentVisibility
from app.services.cms import content_item_service, content_type_service
import copy as copy_module


def get_marketplace_items(
    db: Session,
    content_type_slug: Optional[str] = None,
    search: Optional[str] = None,
    skip: int = 0,
    limit: int = 50
) -> Tuple[List[ContentItem], int]:
    """
    Get items available in the marketplace.
    Returns published items with marketplace visibility.
    """
    query = db.query(ContentItem).filter(
        and_(
            ContentItem.visibility == ContentVisibility.MARKETPLACE.value,
            ContentItem.status == ContentStatus.PUBLISHED.value
        )
    )

    if content_type_slug:
        query = query.join(ContentType).filter(ContentType.slug == content_type_slug)

    if search:
        # Basic search in JSONB data
        from sqlalchemy import String
        query = query.filter(
            ContentItem.data.cast(String).ilike(f'%{search}%')
        )

    total = query.count()
    items = query.order_by(
        ContentItem.is_featured.desc(),
        ContentItem.download_count.desc(),
        ContentItem.created_at.desc()
    ).offset(skip).limit(limit).all()

    return items, total


def get_featured_marketplace_items(
    db: Session,
    limit: int = 10
) -> List[ContentItem]:
    """Get featured marketplace items."""
    return db.query(ContentItem).filter(
        and_(
            ContentItem.visibility == ContentVisibility.MARKETPLACE.value,
            ContentItem.status == ContentStatus.PUBLISHED.value,
            ContentItem.is_featured == True
        )
    ).order_by(ContentItem.download_count.desc()).limit(limit).all()


def get_marketplace_content_types(db: Session) -> List[Dict[str, Any]]:
    """Get content types that have marketplace items."""
    from sqlalchemy import func

    results = db.query(
        ContentType.slug,
        ContentType.name,
        ContentType.icon,
        func.count(ContentItem.id).label('item_count')
    ).join(ContentItem, ContentItem.content_type_id == ContentType.id).filter(
        and_(
            ContentItem.visibility == ContentVisibility.MARKETPLACE.value,
            ContentItem.status == ContentStatus.PUBLISHED.value
        )
    ).group_by(ContentType.slug, ContentType.name, ContentType.icon).all()

    return [
        {
            "slug": r.slug,
            "name": r.name,
            "icon": r.icon,
            "item_count": r.item_count
        }
        for r in results
    ]


def copy_from_marketplace(
    db: Session,
    original_item_id: int,
    target_company_id: int,
    target_user_id: int,
    target_knowledge_base_id: Optional[int] = None
) -> ContentItem:
    """
    Copy a marketplace item to a company's own content.
    Creates a new content item with visibility set to 'private'.
    """
    # Get original item
    original_item = db.query(ContentItem).filter(
        and_(
            ContentItem.id == original_item_id,
            ContentItem.visibility == ContentVisibility.MARKETPLACE.value,
            ContentItem.status == ContentStatus.PUBLISHED.value
        )
    ).first()

    if not original_item:
        raise ValueError("Marketplace item not found or not available for copying")

    # Get original content type
    original_type = db.query(ContentType).filter(
        ContentType.id == original_item.content_type_id
    ).first()

    if not original_type:
        raise ValueError("Content type not found")

    # Check if target company has the same content type, or create it
    target_type = db.query(ContentType).filter(
        and_(
            ContentType.company_id == target_company_id,
            ContentType.slug == original_type.slug
        )
    ).first()

    if not target_type:
        # Create content type in target company
        target_type = ContentType(
            company_id=target_company_id,
            knowledge_base_id=target_knowledge_base_id,
            name=original_type.name,
            slug=original_type.slug,
            description=original_type.description,
            icon=original_type.icon,
            field_schema=copy_module.deepcopy(original_type.field_schema),
            allow_public_publish=original_type.allow_public_publish
        )
        db.add(target_type)
        db.flush()

    # Create copy of the content item
    copied_item = ContentItem(
        content_type_id=target_type.id,
        company_id=target_company_id,
        knowledge_base_id=target_knowledge_base_id,
        data=copy_module.deepcopy(original_item.data),
        status=ContentStatus.DRAFT.value,  # Start as draft
        visibility=ContentVisibility.PRIVATE.value,  # Start as private
        created_by=target_user_id,
        updated_by=target_user_id
    )

    db.add(copied_item)
    db.flush()

    # Track the copy
    copy_record = ContentCopy(
        original_item_id=original_item.id,
        original_company_id=original_item.company_id,
        copied_item_id=copied_item.id,
        copied_by_company_id=target_company_id,
        copied_by_user_id=target_user_id
    )

    db.add(copy_record)

    # Increment download count on original
    original_item.download_count += 1

    db.commit()
    db.refresh(copied_item)

    return copied_item


def get_copy_history(
    db: Session,
    company_id: int,
    skip: int = 0,
    limit: int = 50
) -> List[ContentCopy]:
    """Get history of items copied by a company."""
    return db.query(ContentCopy).filter(
        ContentCopy.copied_by_company_id == company_id
    ).order_by(ContentCopy.copied_at.desc()).offset(skip).limit(limit).all()


def get_item_copy_count(db: Session, item_id: int) -> int:
    """Get how many times an item has been copied."""
    return db.query(ContentCopy).filter(
        ContentCopy.original_item_id == item_id
    ).count()


def set_featured(
    db: Session,
    item_id: int,
    company_id: int,
    is_featured: bool
) -> Optional[ContentItem]:
    """Set or unset an item as featured in the marketplace."""
    item = content_item_service.get_content_item(db, item_id, company_id)
    if not item:
        return None

    if item.visibility != ContentVisibility.MARKETPLACE.value:
        raise ValueError("Only marketplace items can be featured")

    item.is_featured = is_featured
    db.commit()
    db.refresh(item)

    return item


# API Token Management

def create_api_token(
    db: Session,
    company_id: int,
    name: str,
    knowledge_base_id: Optional[int] = None,
    can_read: bool = True,
    can_search: bool = True,
    rate_limit: int = 100,
    expires_at: Optional[datetime] = None
) -> ContentApiToken:
    """Create a new API token for public content access."""
    token = ContentApiToken(
        company_id=company_id,
        knowledge_base_id=knowledge_base_id,
        token=ContentApiToken.generate_token(),
        name=name,
        can_read=can_read,
        can_search=can_search,
        rate_limit=rate_limit,
        expires_at=expires_at
    )

    db.add(token)
    db.commit()
    db.refresh(token)

    return token


def get_api_token(db: Session, token_id: int, company_id: int) -> Optional[ContentApiToken]:
    """Get an API token by ID."""
    return db.query(ContentApiToken).filter(
        and_(
            ContentApiToken.id == token_id,
            ContentApiToken.company_id == company_id
        )
    ).first()


def get_api_token_by_token(db: Session, token: str) -> Optional[ContentApiToken]:
    """Get an API token by its token string."""
    return db.query(ContentApiToken).filter(
        ContentApiToken.token == token
    ).first()


def get_api_tokens(
    db: Session,
    company_id: int,
    knowledge_base_id: Optional[int] = None
) -> List[ContentApiToken]:
    """Get all API tokens for a company."""
    query = db.query(ContentApiToken).filter(ContentApiToken.company_id == company_id)

    if knowledge_base_id:
        query = query.filter(ContentApiToken.knowledge_base_id == knowledge_base_id)

    return query.order_by(ContentApiToken.created_at.desc()).all()


def update_api_token(
    db: Session,
    token_id: int,
    company_id: int,
    name: Optional[str] = None,
    can_read: Optional[bool] = None,
    can_search: Optional[bool] = None,
    rate_limit: Optional[int] = None,
    is_active: Optional[bool] = None,
    expires_at: Optional[datetime] = None
) -> Optional[ContentApiToken]:
    """Update an API token."""
    token = get_api_token(db, token_id, company_id)
    if not token:
        return None

    if name is not None:
        token.name = name
    if can_read is not None:
        token.can_read = can_read
    if can_search is not None:
        token.can_search = can_search
    if rate_limit is not None:
        token.rate_limit = rate_limit
    if is_active is not None:
        token.is_active = is_active
    if expires_at is not None:
        token.expires_at = expires_at

    db.commit()
    db.refresh(token)

    return token


def delete_api_token(db: Session, token_id: int, company_id: int) -> bool:
    """Delete (revoke) an API token."""
    token = get_api_token(db, token_id, company_id)
    if not token:
        return False

    db.delete(token)
    db.commit()

    return True


def validate_api_token(db: Session, token_string: str) -> Tuple[bool, Optional[ContentApiToken], str]:
    """
    Validate an API token.
    Returns (is_valid, token_object, error_message).
    """
    token = get_api_token_by_token(db, token_string)

    if not token:
        return False, None, "Invalid token"

    if not token.is_active:
        return False, None, "Token is inactive"

    if token.expires_at and token.expires_at < datetime.utcnow():
        return False, None, "Token has expired"

    return True, token, ""


def record_token_usage(db: Session, token: ContentApiToken) -> None:
    """Record usage of an API token."""
    token.last_used_at = datetime.utcnow()
    token.request_count += 1
    db.commit()


def regenerate_api_token(db: Session, token_id: int, company_id: int) -> Optional[ContentApiToken]:
    """Regenerate the token string for an API token."""
    token = get_api_token(db, token_id, company_id)
    if not token:
        return None

    token.token = ContentApiToken.generate_token()
    db.commit()
    db.refresh(token)

    return token
