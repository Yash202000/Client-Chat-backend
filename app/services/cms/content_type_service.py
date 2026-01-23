from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_
from app.models.content_type import ContentType
from app.schemas.cms import ContentTypeCreate, ContentTypeUpdate, FieldDefinition
import re


def slugify(text: str) -> str:
    """Convert text to a valid slug."""
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[-\s]+', '-', text)
    return text


def validate_field_schema(field_schema: List[FieldDefinition]) -> List[str]:
    """
    Validate field schema for duplicate slugs and other issues.
    Returns list of error messages.
    """
    errors = []
    slugs = set()

    for field in field_schema:
        if field.slug in slugs:
            errors.append(f"Duplicate field slug: {field.slug}")
        slugs.add(field.slug)

        # Validate relation fields have target_type
        if field.type == "relation":
            if not field.settings or not field.settings.get("target_type"):
                errors.append(f"Relation field '{field.slug}' must have 'target_type' in settings")

        # Validate select fields have options
        if field.type == "select":
            if not field.settings or not field.settings.get("options"):
                errors.append(f"Select field '{field.slug}' must have 'options' in settings")

    return errors


def get_content_type(db: Session, content_type_id: int, company_id: int) -> Optional[ContentType]:
    """Get a content type by ID."""
    return db.query(ContentType).filter(
        and_(
            ContentType.id == content_type_id,
            ContentType.company_id == company_id
        )
    ).first()


def get_content_type_by_slug(db: Session, slug: str, company_id: int) -> Optional[ContentType]:
    """Get a content type by slug."""
    return db.query(ContentType).filter(
        and_(
            ContentType.slug == slug,
            ContentType.company_id == company_id
        )
    ).first()


def get_content_types(
    db: Session,
    company_id: int,
    knowledge_base_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 100
) -> List[ContentType]:
    """Get all content types for a company, optionally filtered by knowledge base."""
    query = db.query(ContentType).filter(ContentType.company_id == company_id)

    if knowledge_base_id is not None:
        query = query.filter(ContentType.knowledge_base_id == knowledge_base_id)

    return query.order_by(ContentType.name).offset(skip).limit(limit).all()


def get_content_types_count(
    db: Session,
    company_id: int,
    knowledge_base_id: Optional[int] = None
) -> int:
    """Get count of content types for a company."""
    query = db.query(ContentType).filter(ContentType.company_id == company_id)

    if knowledge_base_id is not None:
        query = query.filter(ContentType.knowledge_base_id == knowledge_base_id)

    return query.count()


def create_content_type(
    db: Session,
    content_type: ContentTypeCreate,
    company_id: int
) -> ContentType:
    """Create a new content type."""
    # Check for duplicate slug
    existing = get_content_type_by_slug(db, content_type.slug, company_id)
    if existing:
        raise ValueError(f"Content type with slug '{content_type.slug}' already exists")

    # Validate field schema
    if content_type.field_schema:
        errors = validate_field_schema(content_type.field_schema)
        if errors:
            raise ValueError(f"Invalid field schema: {'; '.join(errors)}")

    # Convert field_schema to dict for storage
    field_schema_dict = [field.model_dump() for field in content_type.field_schema]

    db_content_type = ContentType(
        company_id=company_id,
        knowledge_base_id=content_type.knowledge_base_id,
        name=content_type.name,
        slug=content_type.slug,
        description=content_type.description,
        icon=content_type.icon,
        field_schema=field_schema_dict,
        allow_public_publish=content_type.allow_public_publish
    )

    db.add(db_content_type)
    db.commit()
    db.refresh(db_content_type)

    return db_content_type


def update_content_type(
    db: Session,
    content_type_id: int,
    content_type_update: ContentTypeUpdate,
    company_id: int
) -> Optional[ContentType]:
    """Update an existing content type."""
    db_content_type = get_content_type(db, content_type_id, company_id)
    if not db_content_type:
        return None

    update_data = content_type_update.model_dump(exclude_unset=True)

    # Validate field schema if being updated
    if 'field_schema' in update_data and update_data['field_schema']:
        errors = validate_field_schema(content_type_update.field_schema)
        if errors:
            raise ValueError(f"Invalid field schema: {'; '.join(errors)}")
        # Convert to dict for storage
        update_data['field_schema'] = [field.model_dump() for field in content_type_update.field_schema]

    for key, value in update_data.items():
        setattr(db_content_type, key, value)

    db.commit()
    db.refresh(db_content_type)

    return db_content_type


def update_content_type_by_slug(
    db: Session,
    slug: str,
    content_type_update: ContentTypeUpdate,
    company_id: int
) -> Optional[ContentType]:
    """Update an existing content type by slug."""
    db_content_type = get_content_type_by_slug(db, slug, company_id)
    if not db_content_type:
        return None

    return update_content_type(db, db_content_type.id, content_type_update, company_id)


def delete_content_type(db: Session, content_type_id: int, company_id: int) -> bool:
    """Delete a content type and all its content items."""
    db_content_type = get_content_type(db, content_type_id, company_id)
    if not db_content_type:
        return False

    db.delete(db_content_type)
    db.commit()

    return True


def delete_content_type_by_slug(db: Session, slug: str, company_id: int) -> bool:
    """Delete a content type by slug."""
    db_content_type = get_content_type_by_slug(db, slug, company_id)
    if not db_content_type:
        return False

    return delete_content_type(db, db_content_type.id, company_id)


def get_field_schema_as_models(content_type: ContentType) -> List[FieldDefinition]:
    """Convert stored field schema back to Pydantic models."""
    if not content_type.field_schema:
        return []
    return [FieldDefinition(**field) for field in content_type.field_schema]


def add_field_to_schema(
    db: Session,
    content_type_id: int,
    field: FieldDefinition,
    company_id: int
) -> Optional[ContentType]:
    """Add a new field to an existing content type's schema."""
    db_content_type = get_content_type(db, content_type_id, company_id)
    if not db_content_type:
        return None

    current_schema = db_content_type.field_schema or []

    # Check for duplicate slug
    existing_slugs = {f['slug'] for f in current_schema}
    if field.slug in existing_slugs:
        raise ValueError(f"Field with slug '{field.slug}' already exists")

    current_schema.append(field.model_dump())
    db_content_type.field_schema = current_schema

    db.commit()
    db.refresh(db_content_type)

    return db_content_type


def remove_field_from_schema(
    db: Session,
    content_type_id: int,
    field_slug: str,
    company_id: int
) -> Optional[ContentType]:
    """Remove a field from an existing content type's schema."""
    db_content_type = get_content_type(db, content_type_id, company_id)
    if not db_content_type:
        return None

    current_schema = db_content_type.field_schema or []
    new_schema = [f for f in current_schema if f['slug'] != field_slug]

    if len(new_schema) == len(current_schema):
        raise ValueError(f"Field with slug '{field_slug}' not found")

    db_content_type.field_schema = new_schema

    db.commit()
    db.refresh(db_content_type)

    return db_content_type
