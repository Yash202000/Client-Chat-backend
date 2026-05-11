from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional

from app.core.dependencies import get_db, get_current_active_user, require_permission
from app.models.user import User
from app.schemas.custom_field import (
    CustomFieldDefinitionCreate, CustomFieldDefinitionUpdate, CustomFieldDefinitionOut
)
from app.services import custom_field_service

router = APIRouter()


@router.get("/", response_model=List[CustomFieldDefinitionOut])
def list_definitions(
    entity_type: Optional[str] = None,
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    return custom_field_service.get_definitions(
        db, current_user.company_id, entity_type, include_inactive
    )


@router.post("/", response_model=CustomFieldDefinitionOut, dependencies=[Depends(require_permission("settings:write"))])
def create_definition(
    data: CustomFieldDefinitionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    return custom_field_service.create_definition(db, data, current_user.company_id)


@router.put("/{definition_id}", response_model=CustomFieldDefinitionOut, dependencies=[Depends(require_permission("settings:write"))])
def update_definition(
    definition_id: int,
    data: CustomFieldDefinitionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    return custom_field_service.update_definition(db, definition_id, data, current_user.company_id)


@router.delete("/{definition_id}", dependencies=[Depends(require_permission("settings:write"))])
def delete_definition(
    definition_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    custom_field_service.delete_definition(db, definition_id, current_user.company_id)
    return {"ok": True}


@router.post("/reorder", dependencies=[Depends(require_permission("settings:write"))])
def reorder_definitions(
    entity_type: str,
    ordered_ids: List[int],
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    return custom_field_service.reorder_definitions(
        db, current_user.company_id, entity_type, ordered_ids
    )
