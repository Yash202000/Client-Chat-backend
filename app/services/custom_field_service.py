from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert as pg_insert
from typing import List, Optional, Dict, Any
from fastapi import HTTPException
from datetime import datetime

from app.models.custom_field import CustomFieldDefinition, CustomFieldProjectConfig
from app.schemas.custom_field import (
    CustomFieldDefinitionCreate, CustomFieldDefinitionUpdate,
    CustomFieldProjectConfigUpsert,
)


# ── CRUD ──────────────────────────────────────────────────────────────────────

def get_definitions(
    db: Session,
    company_id: int,
    entity_type: Optional[str] = None,
    include_inactive: bool = False,
    project_id: Optional[int] = None,
) -> List[CustomFieldDefinition]:
    """
    Return field definitions for the company.
    When project_id is given:
      - Always include global fields (is_global=True).
      - Include non-global fields only if they have a config row with visible=True for that project.
    """
    q = db.query(CustomFieldDefinition).filter(
        CustomFieldDefinition.company_id == company_id
    )
    if entity_type:
        q = q.filter(CustomFieldDefinition.entity_type == entity_type)
    if not include_inactive:
        q = q.filter(CustomFieldDefinition.is_active == True)

    if project_id is not None:
        from sqlalchemy import or_, and_, exists
        subq = (
            db.query(CustomFieldProjectConfig.field_id)
            .filter(
                CustomFieldProjectConfig.project_id == project_id,
                CustomFieldProjectConfig.visible == True,
            )
            .subquery()
        )
        q = q.filter(
            or_(
                CustomFieldDefinition.is_global == True,
                CustomFieldDefinition.id.in_(subq),
            )
        )

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
        is_global=data.is_global,
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


# ── Project config CRUD ───────────────────────────────────────────────────────

def get_project_configs(
    db: Session, field_id: int, company_id: int
) -> List[CustomFieldProjectConfig]:
    return db.query(CustomFieldProjectConfig).filter(
        CustomFieldProjectConfig.field_id == field_id,
        CustomFieldProjectConfig.company_id == company_id,
    ).all()


def upsert_project_config(
    db: Session,
    field_id: int,
    project_id: int,
    data: CustomFieldProjectConfigUpsert,
    company_id: int,
) -> CustomFieldProjectConfig:
    existing = db.query(CustomFieldProjectConfig).filter(
        CustomFieldProjectConfig.field_id == field_id,
        CustomFieldProjectConfig.project_id == project_id,
    ).first()

    if existing:
        existing.visible = data.visible
        existing.required = data.required
        existing.position = data.position
        existing.group_name = data.group_name
        existing.updated_at = datetime.utcnow()
    else:
        existing = CustomFieldProjectConfig(
            company_id=company_id,
            field_id=field_id,
            project_id=project_id,
            visible=data.visible,
            required=data.required,
            position=data.position,
            group_name=data.group_name,
        )
        db.add(existing)

    db.commit()
    db.refresh(existing)
    return existing


def delete_project_config(
    db: Session, field_id: int, project_id: int, company_id: int
) -> bool:
    cfg = db.query(CustomFieldProjectConfig).filter(
        CustomFieldProjectConfig.field_id == field_id,
        CustomFieldProjectConfig.project_id == project_id,
        CustomFieldProjectConfig.company_id == company_id,
    ).first()
    if cfg:
        db.delete(cfg)
        db.commit()
    return True


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
        elif ft == "hierarchy_node":
            # value must be a string node code; existence validated at API level if needed
            return str(value)
        elif ft == "coordinates":
            if isinstance(value, dict):
                lat = value.get("lat")
                lng = value.get("lng")
            elif isinstance(value, (list, tuple)) and len(value) == 2:
                lat, lng = value[0], value[1]
            else:
                raise HTTPException(status_code=422, detail=f"'{defn.label}' must be {{lat, lng}}")
            try:
                lat, lng = float(lat), float(lng)
            except (TypeError, ValueError):
                raise HTTPException(status_code=422, detail=f"'{defn.label}' lat/lng must be numbers")
            if not (-90 <= lat <= 90):
                raise HTTPException(status_code=422, detail=f"'{defn.label}' latitude must be -90 to 90")
            if not (-180 <= lng <= 180):
                raise HTTPException(status_code=422, detail=f"'{defn.label}' longitude must be -180 to 180")
            return {"lat": lat, "lng": lng}
        else:
            return str(value)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=422, detail=f"Invalid value for '{defn.label}' (expected {ft})")
