from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional
from fastapi import HTTPException

from app.models.hierarchy import HierarchyType, HierarchyNode, UserNodeAssignment, TeamNodeAssignment


# ── Hierarchy Types ───────────────────────────────────────────────────────────

def get_types(db: Session, company_id: int, include_inactive: bool = False) -> List[HierarchyType]:
    q = db.query(HierarchyType).filter(HierarchyType.company_id == company_id)
    if not include_inactive:
        q = q.filter(HierarchyType.is_active == True)
    return q.order_by(HierarchyType.position, HierarchyType.id).all()


def get_type(db: Session, type_id: int, company_id: int) -> Optional[HierarchyType]:
    return db.query(HierarchyType).filter(
        HierarchyType.id == type_id, HierarchyType.company_id == company_id
    ).first()


def create_type(db: Session, company_id: int, name: str, description: str = None) -> HierarchyType:
    ht = HierarchyType(company_id=company_id, name=name, description=description)
    db.add(ht)
    db.commit()
    db.refresh(ht)
    return ht


def update_type(db: Session, type_id: int, company_id: int, **kwargs) -> HierarchyType:
    ht = get_type(db, type_id, company_id)
    if not ht:
        raise HTTPException(status_code=404, detail="Hierarchy type not found")
    for k, v in kwargs.items():
        if v is not None:
            setattr(ht, k, v)
    db.commit()
    db.refresh(ht)
    return ht


def delete_type(db: Session, type_id: int, company_id: int) -> bool:
    ht = get_type(db, type_id, company_id)
    if not ht:
        return False
    db.delete(ht)
    db.commit()
    return True


# ── Hierarchy Nodes ───────────────────────────────────────────────────────────

def _build_path(db: Session, parent_id: Optional[int], node_id: int) -> str:
    """Compute materialized path from root down to node_id."""
    if not parent_id:
        return str(node_id)
    parent = db.query(HierarchyNode).filter(HierarchyNode.id == parent_id).first()
    if not parent:
        return str(node_id)
    return f"{parent.path}.{node_id}"


def get_nodes(db: Session, company_id: int, type_id: int, include_inactive: bool = False) -> List[HierarchyNode]:
    q = db.query(HierarchyNode).filter(
        HierarchyNode.company_id == company_id,
        HierarchyNode.type_id == type_id,
    )
    if not include_inactive:
        q = q.filter(HierarchyNode.is_active == True)
    return q.order_by(HierarchyNode.path, HierarchyNode.position).all()


def get_node(db: Session, node_id: int, company_id: int) -> Optional[HierarchyNode]:
    return db.query(HierarchyNode).filter(
        HierarchyNode.id == node_id, HierarchyNode.company_id == company_id
    ).first()


def create_node(db: Session, company_id: int, type_id: int, name: str, code: str,
                parent_id: Optional[int] = None, metadata: dict = None) -> HierarchyNode:
    ht = get_type(db, type_id, company_id)
    if not ht:
        raise HTTPException(status_code=404, detail="Hierarchy type not found")

    # Check code uniqueness within type
    existing = db.query(HierarchyNode).filter(
        HierarchyNode.company_id == company_id,
        HierarchyNode.type_id == type_id,
        HierarchyNode.code == code,
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Node with code '{code}' already exists in this type")

    node = HierarchyNode(
        company_id=company_id,
        type_id=type_id,
        parent_id=parent_id,
        name=name,
        code=code,
        path="0",  # placeholder, updated after flush
        metadata_=metadata,
    )
    db.add(node)
    db.flush()
    node.path = _build_path(db, parent_id, node.id)
    db.commit()
    db.refresh(node)
    return node


def update_node(db: Session, node_id: int, company_id: int, **kwargs) -> HierarchyNode:
    node = get_node(db, node_id, company_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    old_path = node.path
    for k, v in kwargs.items():
        setattr(node, k, v)

    # Recompute path if parent changed
    if "parent_id" in kwargs:
        node.path = _build_path(db, node.parent_id, node.id)
        new_path = node.path
        # Update all descendant paths (replace old_path prefix with new_path)
        descendants = db.query(HierarchyNode).filter(
            HierarchyNode.path.like(f"{old_path}.%"),
            HierarchyNode.company_id == company_id,
        ).all()
        for d in descendants:
            d.path = new_path + d.path[len(old_path):]

    db.commit()
    db.refresh(node)
    return node


def delete_node(db: Session, node_id: int, company_id: int) -> bool:
    node = get_node(db, node_id, company_id)
    if not node:
        return False
    db.delete(node)
    db.commit()
    return True


def get_tree(db: Session, company_id: int, type_id: int) -> list:
    """Return nodes as a nested tree structure."""
    nodes = get_nodes(db, company_id, type_id, include_inactive=True)
    node_map = {n.id: {
        "id": n.id, "name": n.name, "code": n.code, "path": n.path,
        "parent_id": n.parent_id, "position": n.position,
        "is_active": n.is_active, "metadata": n.metadata_,
        "children": []
    } for n in nodes}
    roots = []
    for n in nodes:
        item = node_map[n.id]
        if n.parent_id and n.parent_id in node_map:
            node_map[n.parent_id]["children"].append(item)
        else:
            roots.append(item)
    return roots


def get_ancestor_node_ids(db: Session, node_id: int, company_id: int) -> List[int]:
    """Return node_id plus all its ancestor node IDs (for ancestor-match routing)."""
    node = get_node(db, node_id, company_id)
    if not node:
        return []
    # path = "1.5.12.47" → split and cast
    return [int(x) for x in node.path.split(".") if x]


def resolve_code_to_node(db: Session, company_id: int, type_id: int, code: str) -> Optional[HierarchyNode]:
    return db.query(HierarchyNode).filter(
        HierarchyNode.company_id == company_id,
        HierarchyNode.type_id == type_id,
        HierarchyNode.code == code,
        HierarchyNode.is_active == True,
    ).first()


# ── User Node Assignments ─────────────────────────────────────────────────────

def get_user_assignments(db: Session, company_id: int, user_id: int) -> List[UserNodeAssignment]:
    return db.query(UserNodeAssignment).filter(
        UserNodeAssignment.company_id == company_id,
        UserNodeAssignment.user_id == user_id,
    ).all()


def assign_node_to_user(db: Session, company_id: int, user_id: int, node_id: int,
                        team_id: int = None) -> UserNodeAssignment:
    existing = db.query(UserNodeAssignment).filter(
        UserNodeAssignment.user_id == user_id,
        UserNodeAssignment.node_id == node_id,
    ).first()
    if existing:
        return existing
    a = UserNodeAssignment(company_id=company_id, user_id=user_id, node_id=node_id, team_id=team_id)
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


def remove_user_assignment(db: Session, assignment_id: int, company_id: int) -> bool:
    a = db.query(UserNodeAssignment).filter(
        UserNodeAssignment.id == assignment_id,
        UserNodeAssignment.company_id == company_id,
    ).first()
    if not a:
        return False
    db.delete(a)
    db.commit()
    return True


def get_users_by_nodes(db: Session, company_id: int, node_ids: List[int],
                       team_id: int = None) -> List[int]:
    """
    Return user IDs that have ALL the given node_ids assigned (with optional team filter).
    Used by the routing engine for node-match assignment.
    """
    if not node_ids:
        return []

    q = db.query(UserNodeAssignment.user_id).filter(
        UserNodeAssignment.company_id == company_id,
        UserNodeAssignment.node_id.in_(node_ids),
    )
    if team_id:
        q = q.filter(UserNodeAssignment.team_id == team_id)

    q = q.group_by(UserNodeAssignment.user_id).having(
        func.count(UserNodeAssignment.node_id.distinct()) >= len(node_ids)
    )
    return [row[0] for row in q.all()]


# ── Team Node Assignments ─────────────────────────────────────────────────────

def get_team_assignments(db: Session, company_id: int, team_id: int) -> List[TeamNodeAssignment]:
    return db.query(TeamNodeAssignment).filter(
        TeamNodeAssignment.company_id == company_id,
        TeamNodeAssignment.team_id == team_id,
    ).all()


def assign_node_to_team(db: Session, company_id: int, team_id: int, node_id: int) -> TeamNodeAssignment:
    existing = db.query(TeamNodeAssignment).filter(
        TeamNodeAssignment.team_id == team_id,
        TeamNodeAssignment.node_id == node_id,
    ).first()
    if existing:
        return existing
    a = TeamNodeAssignment(company_id=company_id, team_id=team_id, node_id=node_id)
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


def remove_team_assignment(db: Session, assignment_id: int, company_id: int) -> bool:
    a = db.query(TeamNodeAssignment).filter(
        TeamNodeAssignment.id == assignment_id,
        TeamNodeAssignment.company_id == company_id,
    ).first()
    if not a:
        return False
    db.delete(a)
    db.commit()
    return True


def get_teams_by_nodes(db: Session, company_id: int, node_ids: List[int]) -> List[int]:
    """Return team IDs that have ALL the given node_ids assigned."""
    if not node_ids:
        return []
    q = db.query(TeamNodeAssignment.team_id).filter(
        TeamNodeAssignment.company_id == company_id,
        TeamNodeAssignment.node_id.in_(node_ids),
    ).group_by(TeamNodeAssignment.team_id).having(
        func.count(TeamNodeAssignment.node_id.distinct()) >= len(node_ids)
    )
    return [row[0] for row in q.all()]
