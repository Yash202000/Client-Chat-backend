from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel, field_validator

from app.core.dependencies import get_db, get_current_active_user
from app.models.user import User
from app.services import hierarchy_service as svc

router = APIRouter()


# ── Schemas ───────────────────────────────────────────────────────────────────

class HierarchyTypeCreate(BaseModel):
    name: str
    description: Optional[str] = None

class HierarchyTypeUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None
    position: Optional[int] = None

class HierarchyTypeOut(BaseModel):
    id: int
    name: str
    description: Optional[str]
    is_active: bool
    position: int
    class Config: from_attributes = True


class HierarchyNodeCreate(BaseModel):
    name: str
    code: str
    parent_id: Optional[int] = None
    metadata: Optional[dict] = None

    @field_validator("code")
    @classmethod
    def validate_code(cls, v):
        if not re.match(r'^[a-z][a-z0-9_]*$', v):
            raise ValueError("code must be lowercase alphanumeric with underscores, starting with a letter")
        return v

class HierarchyNodeUpdate(BaseModel):
    name: Optional[str] = None
    parent_id: Optional[int] = None
    metadata: Optional[dict] = None
    position: Optional[int] = None
    is_active: Optional[bool] = None

class HierarchyNodeOut(BaseModel):
    id: int
    type_id: int
    parent_id: Optional[int]
    name: str
    code: str
    path: str
    position: int
    is_active: bool
    metadata: Optional[dict] = None
    class Config: from_attributes = True

    @classmethod
    def from_orm_custom(cls, node):
        return cls(
            id=node.id, type_id=node.type_id, parent_id=node.parent_id,
            name=node.name, code=node.code, path=node.path,
            position=node.position, is_active=node.is_active, metadata=node.metadata_
        )


class UserNodeAssignCreate(BaseModel):
    user_id: int
    node_id: int
    team_id: Optional[int] = None

class UserNodeAssignOut(BaseModel):
    id: int
    user_id: int
    node_id: int
    team_id: Optional[int]
    class Config: from_attributes = True


class TeamNodeAssignCreate(BaseModel):
    team_id: int
    node_id: int

class TeamNodeAssignOut(BaseModel):
    id: int
    team_id: int
    node_id: int
    class Config: from_attributes = True


# ── Hierarchy Types ───────────────────────────────────────────────────────────

@router.get("/types", response_model=List[HierarchyTypeOut])
def list_types(
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    return svc.get_types(db, current_user.company_id, include_inactive)


@router.post("/types", response_model=HierarchyTypeOut, status_code=201)
def create_type(
    body: HierarchyTypeCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    return svc.create_type(db, current_user.company_id, body.name, body.description)


@router.put("/types/{type_id}", response_model=HierarchyTypeOut)
def update_type(
    type_id: int,
    body: HierarchyTypeUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    return svc.update_type(db, type_id, current_user.company_id, **body.model_dump(exclude_none=True))


@router.delete("/types/{type_id}", status_code=204)
def delete_type(
    type_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    if not svc.delete_type(db, type_id, current_user.company_id):
        raise HTTPException(status_code=404, detail="Hierarchy type not found")


# ── Hierarchy Nodes ───────────────────────────────────────────────────────────

@router.get("/types/{type_id}/nodes", response_model=List[HierarchyNodeOut])
def list_nodes(
    type_id: int,
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    nodes = svc.get_nodes(db, current_user.company_id, type_id, include_inactive)
    return [HierarchyNodeOut.from_orm_custom(n) for n in nodes]


@router.get("/types/{type_id}/tree")
def get_tree(
    type_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    return svc.get_tree(db, current_user.company_id, type_id)


@router.post("/types/{type_id}/nodes", response_model=HierarchyNodeOut, status_code=201)
def create_node(
    type_id: int,
    body: HierarchyNodeCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    node = svc.create_node(
        db, current_user.company_id, type_id,
        body.name, body.code, body.parent_id, body.metadata
    )
    return HierarchyNodeOut.from_orm_custom(node)


@router.put("/nodes/{node_id}", response_model=HierarchyNodeOut)
def update_node(
    node_id: int,
    body: HierarchyNodeUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    updates = body.model_dump(exclude_none=True)
    if "metadata" in updates:
        updates["metadata_"] = updates.pop("metadata")
    node = svc.update_node(db, node_id, current_user.company_id, **updates)
    return HierarchyNodeOut.from_orm_custom(node)


@router.delete("/nodes/{node_id}", status_code=204)
def delete_node(
    node_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    if not svc.delete_node(db, node_id, current_user.company_id):
        raise HTTPException(status_code=404, detail="Node not found")


# ── User Node Assignments ─────────────────────────────────────────────────────

@router.get("/user-assignments", response_model=List[UserNodeAssignOut])
def list_user_assignments(
    user_id: int = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    return svc.get_user_assignments(db, current_user.company_id, user_id)


@router.post("/user-assignments", response_model=UserNodeAssignOut, status_code=201)
def assign_to_user(
    body: UserNodeAssignCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    return svc.assign_node_to_user(
        db, current_user.company_id, body.user_id, body.node_id, body.team_id
    )


@router.delete("/user-assignments/{assignment_id}", status_code=204)
def remove_user_assignment(
    assignment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    if not svc.remove_user_assignment(db, assignment_id, current_user.company_id):
        raise HTTPException(status_code=404, detail="Assignment not found")


# ── Team Node Assignments ─────────────────────────────────────────────────────

@router.get("/team-assignments", response_model=List[TeamNodeAssignOut])
def list_team_assignments(
    team_id: int = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    return svc.get_team_assignments(db, current_user.company_id, team_id)


@router.post("/team-assignments", response_model=TeamNodeAssignOut, status_code=201)
def assign_to_team(
    body: TeamNodeAssignCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    return svc.assign_node_to_team(db, current_user.company_id, body.team_id, body.node_id)


@router.delete("/team-assignments/{assignment_id}", status_code=204)
def remove_team_assignment(
    assignment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    if not svc.remove_team_assignment(db, assignment_id, current_user.company_id):
        raise HTTPException(status_code=404, detail="Assignment not found")
