from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List, Optional

from app.core.dependencies import get_db, get_current_active_user, require_permission
from app.models.user import User
from app.schemas.routing_rule import RoutingRuleCreate, RoutingRuleUpdate, RoutingRuleOut
from app.services import routing_service

router = APIRouter()


@router.get("/", response_model=List[RoutingRuleOut])
def list_rules(
    entity_type: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    return routing_service.get_rules(db, current_user.company_id, entity_type)


@router.post("/", response_model=RoutingRuleOut, dependencies=[Depends(require_permission("settings:write"))])
def create_rule(
    data: RoutingRuleCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    return routing_service.create_rule(db, data, current_user.company_id)


@router.put("/{rule_id}", response_model=RoutingRuleOut, dependencies=[Depends(require_permission("settings:write"))])
def update_rule(
    rule_id: int,
    data: RoutingRuleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    return routing_service.update_rule(db, rule_id, data, current_user.company_id)


@router.delete("/{rule_id}", dependencies=[Depends(require_permission("settings:write"))])
def delete_rule(
    rule_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    routing_service.delete_rule(db, rule_id, current_user.company_id)
    return {"ok": True}


@router.post("/reorder", dependencies=[Depends(require_permission("settings:write"))])
def reorder_rules(
    entity_type: str,
    ordered_ids: List[int],
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    return routing_service.reorder_rules(db, current_user.company_id, entity_type, ordered_ids)
