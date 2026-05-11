from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional
from fastapi import HTTPException

from app.models.department import Department, DepartmentNodeAssignment, DepartmentUserMembership
from app.models.hierarchy import HierarchyNode


# ── Departments ───────────────────────────────────────────────────────────────

def get_departments(db: Session, company_id: int, include_inactive: bool = False) -> List[Department]:
    q = db.query(Department).filter(Department.company_id == company_id)
    if not include_inactive:
        q = q.filter(Department.is_active == True)
    return q.order_by(Department.name).all()


def get_department(db: Session, dept_id: int, company_id: int) -> Optional[Department]:
    return db.query(Department).filter(
        Department.id == dept_id, Department.company_id == company_id
    ).first()


def create_department(db: Session, company_id: int, name: str, description: str = None) -> Department:
    dept = Department(company_id=company_id, name=name, description=description)
    db.add(dept)
    db.commit()
    db.refresh(dept)
    return dept


def update_department(db: Session, dept_id: int, company_id: int, **kwargs) -> Department:
    dept = get_department(db, dept_id, company_id)
    if not dept:
        raise HTTPException(status_code=404, detail="Department not found")
    for k, v in kwargs.items():
        setattr(dept, k, v)
    db.commit()
    db.refresh(dept)
    return dept


def delete_department(db: Session, dept_id: int, company_id: int) -> bool:
    dept = get_department(db, dept_id, company_id)
    if not dept:
        return False
    db.delete(dept)
    db.commit()
    return True


# ── Node Assignments ──────────────────────────────────────────────────────────

def get_node_assignments(db: Session, company_id: int, dept_id: int) -> List[DepartmentNodeAssignment]:
    return db.query(DepartmentNodeAssignment).filter(
        DepartmentNodeAssignment.company_id == company_id,
        DepartmentNodeAssignment.department_id == dept_id,
    ).all()


def assign_node(db: Session, company_id: int, dept_id: int, node_id: int) -> DepartmentNodeAssignment:
    existing = db.query(DepartmentNodeAssignment).filter(
        DepartmentNodeAssignment.department_id == dept_id,
        DepartmentNodeAssignment.node_id == node_id,
    ).first()
    if existing:
        return existing
    a = DepartmentNodeAssignment(company_id=company_id, department_id=dept_id, node_id=node_id)
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


def remove_node_assignment(db: Session, assignment_id: int, company_id: int) -> bool:
    a = db.query(DepartmentNodeAssignment).filter(
        DepartmentNodeAssignment.id == assignment_id,
        DepartmentNodeAssignment.company_id == company_id,
    ).first()
    if not a:
        return False
    db.delete(a)
    db.commit()
    return True


# ── User Memberships ──────────────────────────────────────────────────────────

def get_memberships(db: Session, company_id: int, dept_id: int) -> List[DepartmentUserMembership]:
    return db.query(DepartmentUserMembership).filter(
        DepartmentUserMembership.company_id == company_id,
        DepartmentUserMembership.department_id == dept_id,
    ).all()


def add_member(db: Session, company_id: int, dept_id: int,
               user_id: int, role: str = "agent") -> DepartmentUserMembership:
    existing = db.query(DepartmentUserMembership).filter(
        DepartmentUserMembership.department_id == dept_id,
        DepartmentUserMembership.user_id == user_id,
        DepartmentUserMembership.role == role,
    ).first()
    if existing:
        return existing
    m = DepartmentUserMembership(company_id=company_id, department_id=dept_id, user_id=user_id, role=role)
    db.add(m)
    db.commit()
    db.refresh(m)
    return m


def remove_member(db: Session, membership_id: int, company_id: int) -> bool:
    m = db.query(DepartmentUserMembership).filter(
        DepartmentUserMembership.id == membership_id,
        DepartmentUserMembership.company_id == company_id,
    ).first()
    if not m:
        return False
    db.delete(m)
    db.commit()
    return True


# ── Routing helpers ───────────────────────────────────────────────────────────

def find_departments_by_nodes(db: Session, company_id: int,
                               node_id_sets: List[set]) -> List[int]:
    """
    Return department IDs that have at least one assignment in EACH of the given
    node_id_sets (one set per routing field, already expanded with ancestor IDs).
    """
    if not node_id_sets:
        return []

    candidate_sets: List[set] = []
    for node_ids in node_id_sets:
        rows = db.query(DepartmentNodeAssignment.department_id).filter(
            DepartmentNodeAssignment.company_id == company_id,
            DepartmentNodeAssignment.node_id.in_(list(node_ids)),
        ).distinct().all()
        candidate_sets.append({r[0] for r in rows})

    if not candidate_sets:
        return []
    matched = candidate_sets[0].intersection(*candidate_sets[1:])
    return list(matched)


def find_users_in_departments(db: Session, company_id: int,
                               dept_ids: List[int], role: str = None) -> List[int]:
    """Return user IDs that are members of any of the given departments with optional role filter."""
    if not dept_ids:
        return []
    q = db.query(DepartmentUserMembership.user_id).filter(
        DepartmentUserMembership.company_id == company_id,
        DepartmentUserMembership.department_id.in_(dept_ids),
    )
    if role:
        q = q.filter(DepartmentUserMembership.role == role)
    return [r[0] for r in q.distinct().all()]
