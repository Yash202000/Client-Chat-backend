from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
from fastapi import HTTPException

from app.models.custom_field import CustomFieldDefinition
from app.schemas.custom_field import CustomFieldDefinitionCreate, CustomFieldDefinitionUpdate


# ── CRUD ──────────────────────────────────────────────────────────────────────

def get_definitions(
    db: Session,
    company_id: int,
    entity_type: Optional[str] = None,
    include_inactive: bool = False,
) -> List[CustomFieldDefinition]:
    q = db.query(CustomFieldDefinition).filter(
        CustomFieldDefinition.company_id == company_id
    )
    if entity_type:
        q = q.filter(CustomFieldDefinition.entity_type == entity_type)
    if not include_inactive:
        q = q.filter(CustomFieldDefinition.is_active == True)
    return q.order_by(CustomFieldDefinition.entity_type, CustomFieldDefinition.position).all()


def get_definition(db: Session, definition_id: int, company_id: int) -> Optional[CustomFieldDefinition]:
    return db.query(CustomFieldDefinition).filter(
        CustomFieldDefinition.id == definition_id,
        CustomFieldDefinition.company_id == company_id,
    ).first()


def create_definition(
    db: Session, data: CustomFieldDefinitionCreate, company_id: int
) -> CustomFieldDefinition:
    # Enforce unique name per company+entity_type
    existing = db.query(CustomFieldDefinition).filter(
        CustomFieldDefinition.company_id == company_id,
        CustomFieldDefinition.entity_type == data.entity_type,
        CustomFieldDefinition.name == data.name,
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Field '{data.name}' already exists for {data.entity_type}")

    opts = None
    if data.options:
        opts = [o.model_dump() for o in data.options]

    defn = CustomFieldDefinition(
        company_id=company_id,
        entity_type=data.entity_type,
        name=data.name,
        label=data.label,
        field_type=data.field_type,
        options=opts,
        required=data.required,
        default_value=data.default_value,
        position=data.position,
        is_active=data.is_active,
        group_name=data.group_name,
    )
    db.add(defn)
    db.commit()
    db.refresh(defn)
    return defn


def update_definition(
    db: Session, definition_id: int, data: CustomFieldDefinitionUpdate, company_id: int
) -> CustomFieldDefinition:
    defn = get_definition(db, definition_id, company_id)
    if not defn:
        raise HTTPException(status_code=404, detail="Custom field definition not found")

    for field, value in data.model_dump(exclude_unset=True).items():
        if field == "options" and value is not None:
            value = [o if isinstance(o, dict) else o.model_dump() for o in value]
        setattr(defn, field, value)

    db.commit()
    db.refresh(defn)
    return defn


def delete_definition(db: Session, definition_id: int, company_id: int) -> bool:
    defn = get_definition(db, definition_id, company_id)
    if not defn:
        raise HTTPException(status_code=404, detail="Custom field definition not found")
    db.delete(defn)
    db.commit()
    return True


def reorder_definitions(
    db: Session, company_id: int, entity_type: str, ordered_ids: List[int]
) -> List[CustomFieldDefinition]:
    """Bulk-update position based on ordered list of IDs."""
    for pos, defn_id in enumerate(ordered_ids):
        db.query(CustomFieldDefinition).filter(
            CustomFieldDefinition.id == defn_id,
            CustomFieldDefinition.company_id == company_id,
            CustomFieldDefinition.entity_type == entity_type,
        ).update({"position": pos})
    db.commit()
    return get_definitions(db, company_id, entity_type)


# ── Value validation ───────────────────────────────────────────────────────────

def validate_custom_field_values(
    db: Session,
    company_id: int,
    entity_type: str,
    field_values: Dict[str, Any],
    required_only: bool = False,
) -> Dict[str, Any]:
    """
    Validate field_values dict against CustomFieldDefinitions.
    Returns cleaned/coerced values.
    Raises HTTPException 422 on validation failure.
    """
    definitions = {
        d.name: d
        for d in get_definitions(db, company_id, entity_type)
    }

    cleaned: Dict[str, Any] = {}

    # Check required fields when required_only=False (full save context)
    if not required_only:
        for name, defn in definitions.items():
            if defn.required and name not in field_values:
                raise HTTPException(status_code=422, detail=f"'{defn.label}' is required")

    for name, value in field_values.items():
        if name not in definitions:
            # Unknown field — skip silently (forward-compat)
            continue
        defn = definitions[name]
        cleaned[name] = _coerce_and_validate(defn, value)

    return cleaned


def _coerce_and_validate(defn: CustomFieldDefinition, value: Any) -> Any:
    """Type-check and coerce a single value against its definition."""
    ft = defn.field_type

    if value is None or value == "":
        if defn.required:
            raise HTTPException(status_code=422, detail=f"'{defn.label}' is required")
        return None

    try:
        if ft == "number":
            return int(value)
        elif ft == "decimal":
            return float(value)
        elif ft == "boolean":
            if isinstance(value, bool):
                return value
            return str(value).lower() in ("true", "1", "yes")
        elif ft == "dropdown":
            allowed = {o["value"] for o in (defn.options or [])}
            if allowed and value not in allowed:
                raise HTTPException(status_code=422, detail=f"'{value}' is not a valid option for '{defn.label}'")
            return value
        elif ft == "multi_select":
            if not isinstance(value, list):
                value = [value]
            allowed = {o["value"] for o in (defn.options or [])}
            if allowed:
                invalid = [v for v in value if v not in allowed]
                if invalid:
                    raise HTTPException(status_code=422, detail=f"Invalid options for '{defn.label}': {invalid}")
            return value
        elif ft == "user_picker":
            return int(value)
        else:
            return str(value)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=422, detail=f"Invalid value for '{defn.label}' (expected {ft})")
