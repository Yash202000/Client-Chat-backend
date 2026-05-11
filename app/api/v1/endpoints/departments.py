from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel, field_validator

from app.core.dependencies import get_db, get_current_active_user
from app.models.user import User
from app.services import department_service as svc

router = APIRouter()


# ── Schemas ───────────────────────────────────────────────────────────────────

class DepartmentCreate(BaseModel):
    name: str
    description: Optional[str] = None

class DepartmentUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None

class DepartmentOut(BaseModel):
    id: int
    name: str
    description: Optional[str]
    is_active: bool
    class Config: from_attributes = True


class NodeAssignCreate(BaseModel):
    node_id: int

class NodeAssignOut(BaseModel):
    id: int
    department_id: int
    node_id: int
    class Config: from_attributes = True


class MemberCreate(BaseModel):
    user_id: int
    role: str = "agent"

    @field_validator("role")
    @classmethod
    def validate_role(cls, v):
        allowed = {"agent", "supervisor", "approver", "manager"}
        if v not in allowed:
            raise ValueError(f"role must be one of {allowed}")
        return v

class MemberOut(BaseModel):
    id: int
    department_id: int
    user_id: int
    role: str
    class Config: from_attributes = True


# ── Departments ───────────────────────────────────────────────────────────────

@router.get("", response_model=List[DepartmentOut])
def list_departments(
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    return svc.get_departments(db, current_user.company_id, include_inactive)


@router.post("", response_model=DepartmentOut, status_code=201)
def create_department(
    body: DepartmentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    return svc.create_department(db, current_user.company_id, body.name, body.description)


@router.put("/{dept_id}", response_model=DepartmentOut)
def update_department(
    dept_id: int,
    body: DepartmentUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    return svc.update_department(db, dept_id, current_user.company_id, **body.model_dump(exclude_none=True))


@router.delete("/{dept_id}", status_code=204)
def delete_department(
    dept_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    if not svc.delete_department(db, dept_id, current_user.company_id):
        raise HTTPException(status_code=404, detail="Department not found")


# ── Node Assignments ──────────────────────────────────────────────────────────

@router.get("/{dept_id}/nodes", response_model=List[NodeAssignOut])
def list_node_assignments(
    dept_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    return svc.get_node_assignments(db, current_user.company_id, dept_id)


@router.post("/{dept_id}/nodes", response_model=NodeAssignOut, status_code=201)
def assign_node(
    dept_id: int,
    body: NodeAssignCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    return svc.assign_node(db, current_user.company_id, dept_id, body.node_id)


@router.delete("/{dept_id}/nodes/{assignment_id}", status_code=204)
def remove_node_assignment(
    dept_id: int,
    assignment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    if not svc.remove_node_assignment(db, assignment_id, current_user.company_id):
        raise HTTPException(status_code=404, detail="Assignment not found")


# ── User Memberships ──────────────────────────────────────────────────────────

@router.get("/{dept_id}/members", response_model=List[MemberOut])
def list_members(
    dept_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    return svc.get_memberships(db, current_user.company_id, dept_id)


@router.post("/{dept_id}/members", response_model=MemberOut, status_code=201)
def add_member(
    dept_id: int,
    body: MemberCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    return svc.add_member(db, current_user.company_id, dept_id, body.user_id, body.role)


@router.delete("/{dept_id}/members/{membership_id}", status_code=204)
def remove_member(
    dept_id: int,
    membership_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    if not svc.remove_member(db, membership_id, current_user.company_id):
        raise HTTPException(status_code=404, detail="Membership not found")
