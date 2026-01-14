from typing import List, Optional, Dict, Any, Tuple
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, or_
from datetime import datetime
from app.models.content_item import ContentItem
from app.models.content_type import ContentType
from app.models.content_category import ContentCategory
from app.schemas.cms import (
    ContentItemCreate,
    ContentItemUpdate,
    ContentStatus,
    ContentVisibility,
    FieldType
)
from app.services.cms import content_type_service
import re


def _index_if_published(db: Session, content_item, content_type):
    """Helper to index content item if it's published."""
    from app.services.cms import search_service
    if content_item.status == ContentStatus.PUBLISHED.value:
        try:
            doc_id = search_service.index_content_item(db, content_item, content_type)
            if doc_id and doc_id != content_item.chroma_doc_id:
                content_item.chroma_doc_id = doc_id
                db.commit()
        except Exception as e:
            print(f"Warning: Failed to index content item {content_item.id}: {e}")


def validate_field_value(field_def: Dict[str, Any], value: Any) -> Tuple[bool, str]:
    """
    Validate a field value against its definition.
    Returns (is_valid, error_message).
    """
    field_type = field_def.get('type')
    field_name = field_def.get('name', field_def.get('slug'))
    required = field_def.get('required', False)

    # Check required
    if required and (value is None or value == '' or value == []):
        return False, f"Field '{field_name}' is required"

    # Skip validation if value is empty and not required
    if value is None or value == '':
        return True, ""

    # Type-specific validation
    if field_type == FieldType.TEXT.value:
        if not isinstance(value, str):
            return False, f"Field '{field_name}' must be a string"

    elif field_type == FieldType.RICH_TEXT.value:
        if not isinstance(value, str):
            return False, f"Field '{field_name}' must be a string"

    elif field_type == FieldType.NUMBER.value:
        if not isinstance(value, (int, float)):
            return False, f"Field '{field_name}' must be a number"

    elif field_type == FieldType.BOOLEAN.value:
        if not isinstance(value, bool):
            return False, f"Field '{field_name}' must be a boolean"

    elif field_type == FieldType.DATE.value:
        if isinstance(value, str):
            try:
                datetime.strptime(value, '%Y-%m-%d')
            except ValueError:
                return False, f"Field '{field_name}' must be a valid date (YYYY-MM-DD)"
        else:
            return False, f"Field '{field_name}' must be a date string"

    elif field_type == FieldType.DATETIME.value:
        if isinstance(value, str):
            try:
                datetime.fromisoformat(value.replace('Z', '+00:00'))
            except ValueError:
                return False, f"Field '{field_name}' must be a valid datetime (ISO format)"
        else:
            return False, f"Field '{field_name}' must be a datetime string"

    elif field_type == FieldType.SELECT.value:
        settings = field_def.get('settings', {})
        options = settings.get('options', [])
        if options and value not in options:
            return False, f"Field '{field_name}' must be one of: {', '.join(options)}"

    elif field_type in [FieldType.MEDIA.value, FieldType.AUDIO.value, FieldType.VIDEO.value, FieldType.FILE.value]:
        # Can be an int (media_id) or dict with media_id
        settings = field_def.get('settings', {})
        multiple = settings.get('multiple', False)
        if multiple:
            if not isinstance(value, list):
                return False, f"Field '{field_name}' must be a list of media IDs"
        else:
            if not isinstance(value, (int, dict)):
                return False, f"Field '{field_name}' must be a media ID or media object"

    elif field_type == FieldType.RELATION.value:
        settings = field_def.get('settings', {})
        multiple = settings.get('multiple', False)
        if multiple:
            if not isinstance(value, list):
                return False, f"Field '{field_name}' must be a list of IDs"
            if not all(isinstance(v, int) for v in value):
                return False, f"Field '{field_name}' must contain only integer IDs"
        else:
            if not isinstance(value, int):
                return False, f"Field '{field_name}' must be an integer ID"

    elif field_type == FieldType.TAGS.value:
        if not isinstance(value, list):
            return False, f"Field '{field_name}' must be a list of tags"

    elif field_type == FieldType.URL.value:
        if isinstance(value, str):
            url_pattern = re.compile(
                r'^https?://'
                r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|'
                r'localhost|'
                r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'
                r'(?::\d+)?'
                r'(?:/?|[/?]\S+)$', re.IGNORECASE)
            if not url_pattern.match(value):
                return False, f"Field '{field_name}' must be a valid URL"
        else:
            return False, f"Field '{field_name}' must be a URL string"

    elif field_type == FieldType.EMAIL.value:
        if isinstance(value, str):
            email_pattern = re.compile(r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$')
            if not email_pattern.match(value):
                return False, f"Field '{field_name}' must be a valid email"
        else:
            return False, f"Field '{field_name}' must be an email string"

    elif field_type == FieldType.JSON.value:
        if not isinstance(value, (dict, list)):
            return False, f"Field '{field_name}' must be a JSON object or array"

    return True, ""


def validate_content_data(content_type: ContentType, data: Dict[str, Any]) -> List[str]:
    """
    Validate content data against the content type's field schema.
    Returns list of error messages.
    """
    errors = []
    field_schema = content_type.field_schema or []

    # Create a map of field definitions
    field_map = {f['slug']: f for f in field_schema}

    # Validate each field in the schema
    for field_def in field_schema:
        slug = field_def['slug']
        value = data.get(slug)
        is_valid, error = validate_field_value(field_def, value)
        if not is_valid:
            errors.append(error)

    # Warn about unknown fields (but don't fail)
    for key in data.keys():
        if key not in field_map:
            # Allow unknown fields but could log warning
            pass

    return errors


def get_content_item(db: Session, item_id: int, company_id: int) -> Optional[ContentItem]:
    """Get a content item by ID."""
    return db.query(ContentItem).options(
        joinedload(ContentItem.categories)
    ).filter(
        and_(
            ContentItem.id == item_id,
            ContentItem.company_id == company_id
        )
    ).first()


def get_content_items(
    db: Session,
    company_id: int,
    content_type_id: Optional[int] = None,
    knowledge_base_id: Optional[int] = None,
    status: Optional[ContentStatus] = None,
    visibility: Optional[ContentVisibility] = None,
    created_by: Optional[int] = None,
    search_query: Optional[str] = None,
    skip: int = 0,
    limit: int = 50
) -> List[ContentItem]:
    """Get content items with filters."""
    query = db.query(ContentItem).options(
        joinedload(ContentItem.categories)
    ).filter(ContentItem.company_id == company_id)

    if content_type_id:
        query = query.filter(ContentItem.content_type_id == content_type_id)

    if knowledge_base_id:
        query = query.filter(ContentItem.knowledge_base_id == knowledge_base_id)

    if status:
        query = query.filter(ContentItem.status == status.value)

    if visibility:
        query = query.filter(ContentItem.visibility == visibility.value)

    if created_by:
        query = query.filter(ContentItem.created_by == created_by)

    # Basic text search in JSONB data (PostgreSQL)
    if search_query:
        # Search in the JSONB data column - this is a simple contains search
        query = query.filter(
            ContentItem.data.cast(db.bind.dialect.type_descriptor(db.String)).ilike(f'%{search_query}%')
        )

    return query.order_by(ContentItem.created_at.desc()).offset(skip).limit(limit).all()


def get_content_items_count(
    db: Session,
    company_id: int,
    content_type_id: Optional[int] = None,
    knowledge_base_id: Optional[int] = None,
    status: Optional[ContentStatus] = None,
    visibility: Optional[ContentVisibility] = None
) -> int:
    """Get count of content items with filters."""
    query = db.query(ContentItem).filter(ContentItem.company_id == company_id)

    if content_type_id:
        query = query.filter(ContentItem.content_type_id == content_type_id)

    if knowledge_base_id:
        query = query.filter(ContentItem.knowledge_base_id == knowledge_base_id)

    if status:
        query = query.filter(ContentItem.status == status.value)

    if visibility:
        query = query.filter(ContentItem.visibility == visibility.value)

    return query.count()


def get_content_items_by_type_slug(
    db: Session,
    type_slug: str,
    company_id: int,
    status: Optional[ContentStatus] = None,
    visibility: Optional[ContentVisibility] = None,
    skip: int = 0,
    limit: int = 50
) -> Tuple[List[ContentItem], int]:
    """Get content items by content type slug."""
    content_type = content_type_service.get_content_type_by_slug(db, type_slug, company_id)
    if not content_type:
        return [], 0

    items = get_content_items(
        db=db,
        company_id=company_id,
        content_type_id=content_type.id,
        status=status,
        visibility=visibility,
        skip=skip,
        limit=limit
    )

    total = get_content_items_count(
        db=db,
        company_id=company_id,
        content_type_id=content_type.id,
        status=status,
        visibility=visibility
    )

    return items, total


def create_content_item(
    db: Session,
    content_item: ContentItemCreate,
    content_type_id: int,
    company_id: int,
    user_id: int
) -> ContentItem:
    """Create a new content item."""
    # Get content type for validation
    content_type = content_type_service.get_content_type(db, content_type_id, company_id)
    if not content_type:
        raise ValueError("Content type not found")

    # Validate data against schema
    errors = validate_content_data(content_type, content_item.data)
    if errors:
        raise ValueError(f"Validation errors: {'; '.join(errors)}")

    db_item = ContentItem(
        content_type_id=content_type_id,
        company_id=company_id,
        knowledge_base_id=content_item.knowledge_base_id or content_type.knowledge_base_id,
        data=content_item.data,
        status=content_item.status.value,
        visibility=content_item.visibility.value,
        created_by=user_id,
        updated_by=user_id
    )

    db.add(db_item)
    db.commit()
    db.refresh(db_item)

    # Handle categories if provided
    if content_item.category_ids:
        update_item_categories(db, db_item.id, content_item.category_ids, company_id)
        db.refresh(db_item)

    # Index in ChromaDB if published
    _index_if_published(db, db_item, content_type)

    return db_item


def create_content_item_by_type_slug(
    db: Session,
    type_slug: str,
    content_item: ContentItemCreate,
    company_id: int,
    user_id: int
) -> ContentItem:
    """Create a content item using content type slug."""
    content_type = content_type_service.get_content_type_by_slug(db, type_slug, company_id)
    if not content_type:
        raise ValueError(f"Content type '{type_slug}' not found")

    return create_content_item(
        db=db,
        content_item=content_item,
        content_type_id=content_type.id,
        company_id=company_id,
        user_id=user_id
    )


def update_content_item(
    db: Session,
    item_id: int,
    content_item_update: ContentItemUpdate,
    company_id: int,
    user_id: int
) -> Optional[ContentItem]:
    """Update an existing content item."""
    db_item = get_content_item(db, item_id, company_id)
    if not db_item:
        return None

    update_data = content_item_update.model_dump(exclude_unset=True)

    # Validate data if being updated
    if 'data' in update_data:
        content_type = content_type_service.get_content_type(db, db_item.content_type_id, company_id)
        if content_type:
            # Merge existing data with updates for validation
            merged_data = {**db_item.data, **update_data['data']}
            errors = validate_content_data(content_type, merged_data)
            if errors:
                raise ValueError(f"Validation errors: {'; '.join(errors)}")
            update_data['data'] = merged_data

    # Handle status changes
    if 'status' in update_data:
        update_data['status'] = update_data['status'].value
        if update_data['status'] == ContentStatus.PUBLISHED.value and not db_item.published_at:
            db_item.published_at = datetime.utcnow()

    # Handle visibility changes
    if 'visibility' in update_data:
        update_data['visibility'] = update_data['visibility'].value

    # Handle categories
    category_ids = update_data.pop('category_ids', None)
    if category_ids is not None:
        update_item_categories(db, item_id, category_ids, company_id)

    # Update fields
    for key, value in update_data.items():
        setattr(db_item, key, value)

    db_item.updated_by = user_id
    db_item.version += 1

    db.commit()
    db.refresh(db_item)

    # Re-index in ChromaDB if published (or remove if unpublished)
    content_type = content_type_service.get_content_type(db, db_item.content_type_id, company_id)
    if content_type:
        if db_item.status == ContentStatus.PUBLISHED.value:
            _index_if_published(db, db_item, content_type)
        elif db_item.chroma_doc_id:
            # Remove from index if no longer published
            _remove_from_index(db, db_item)

    return db_item


def _remove_from_index(db: Session, content_item: ContentItem) -> None:
    """Helper to remove content item from ChromaDB index."""
    from app.services.cms import search_service
    if content_item.chroma_doc_id:
        try:
            search_service.remove_content_item_from_index(
                company_id=content_item.company_id,
                chroma_doc_id=content_item.chroma_doc_id,
                knowledge_base_id=content_item.knowledge_base_id,
                db=db  # Pass db for KB collection lookup
            )
        except Exception as e:
            print(f"Warning: Failed to remove content item {content_item.id} from index: {e}")


def delete_content_item(db: Session, item_id: int, company_id: int) -> bool:
    """Delete a content item."""
    db_item = get_content_item(db, item_id, company_id)
    if not db_item:
        return False

    # Remove from ChromaDB index first
    _remove_from_index(db, db_item)

    db.delete(db_item)
    db.commit()

    return True


def update_item_categories(
    db: Session,
    item_id: int,
    category_ids: List[int],
    company_id: int
) -> None:
    """Update the categories for a content item."""
    db_item = get_content_item(db, item_id, company_id)
    if not db_item:
        return

    # Get valid categories
    categories = db.query(ContentCategory).filter(
        and_(
            ContentCategory.id.in_(category_ids),
            ContentCategory.company_id == company_id
        )
    ).all()

    db_item.categories = categories
    db.commit()


def publish_content_item(db: Session, item_id: int, company_id: int, user_id: int) -> Optional[ContentItem]:
    """Publish a content item."""
    db_item = get_content_item(db, item_id, company_id)
    if not db_item:
        return None

    db_item.status = ContentStatus.PUBLISHED.value
    db_item.published_at = datetime.utcnow()
    db_item.updated_by = user_id

    db.commit()
    db.refresh(db_item)

    # Index in ChromaDB now that it's published
    content_type = content_type_service.get_content_type(db, db_item.content_type_id, company_id)
    if content_type:
        _index_if_published(db, db_item, content_type)

    return db_item


def archive_content_item(db: Session, item_id: int, company_id: int, user_id: int) -> Optional[ContentItem]:
    """Archive a content item."""
    db_item = get_content_item(db, item_id, company_id)
    if not db_item:
        return None

    # Remove from ChromaDB index since archived content shouldn't be searchable
    _remove_from_index(db, db_item)

    db_item.status = ContentStatus.ARCHIVED.value
    db_item.updated_by = user_id

    db.commit()
    db.refresh(db_item)

    return db_item


def change_visibility(
    db: Session,
    item_id: int,
    visibility: ContentVisibility,
    company_id: int,
    user_id: int
) -> Optional[ContentItem]:
    """Change the visibility of a content item."""
    db_item = get_content_item(db, item_id, company_id)
    if not db_item:
        return None

    # Check if content type allows public publishing
    if visibility in [ContentVisibility.MARKETPLACE, ContentVisibility.PUBLIC]:
        content_type = content_type_service.get_content_type(db, db_item.content_type_id, company_id)
        if content_type and not content_type.allow_public_publish:
            raise ValueError("This content type does not allow public publishing")

    db_item.visibility = visibility.value
    db_item.updated_by = user_id

    db.commit()
    db.refresh(db_item)

    return db_item


def get_marketplace_items(
    db: Session,
    content_type_slug: Optional[str] = None,
    skip: int = 0,
    limit: int = 50
) -> Tuple[List[ContentItem], int]:
    """Get items available in the marketplace (visibility = marketplace)."""
    query = db.query(ContentItem).filter(
        and_(
            ContentItem.visibility == ContentVisibility.MARKETPLACE.value,
            ContentItem.status == ContentStatus.PUBLISHED.value
        )
    )

    if content_type_slug:
        query = query.join(ContentType).filter(ContentType.slug == content_type_slug)

    total = query.count()
    items = query.order_by(ContentItem.download_count.desc(), ContentItem.created_at.desc()).offset(skip).limit(limit).all()

    return items, total


def increment_download_count(db: Session, item_id: int) -> None:
    """Increment the download count for a marketplace item."""
    db_item = db.query(ContentItem).filter(ContentItem.id == item_id).first()
    if db_item:
        db_item.download_count += 1
        db.commit()
