"""
Rule-based routing engine for tickets, leads, and deals.

Evaluation flow:
  1. Load active rules for company + entity_type, ordered by priority ASC.
  2. For each rule, evaluate conditions against the entity.
  3. First matching rule wins → execute action (assign user/team/skill).
  4. Stop after first match.
"""
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Optional, Any, List
from datetime import datetime

from app.models.routing_rule import RoutingRule, RoutingRoundRobinState
from app.models.team_membership import TeamMembership
from app.models.user import User
from app.models.hierarchy import HierarchyNode, UserNodeAssignment
from app.services import department_service as dept_svc


# ── Public entry point ────────────────────────────────────────────────────────

def evaluate_and_route(
    db: Session,
    entity,
    entity_type: str,
    company_id: int,
    trigger: str = "on_create",
    transition_id: Optional[int] = None,
) -> Optional[int]:
    """
    Evaluate routing rules for an entity and apply the first matching action.
    Returns the assigned user_id if an assignment was made, else None.
    """
    rules = _load_rules(db, company_id, entity_type, trigger, transition_id)

    for rule in rules:
        if _matches_conditions(entity, rule.conditions or []):
            assigned_id = _execute_action(db, rule, company_id, entity=entity)
            if assigned_id and hasattr(entity, "assignee_id") and entity.assignee_id is None:
                entity.assignee_id = assigned_id
            return assigned_id

    return None


# ── Rule loading ──────────────────────────────────────────────────────────────

def _load_rules(
    db: Session,
    company_id: int,
    entity_type: str,
    trigger: str,
    transition_id: Optional[int],
) -> List[RoutingRule]:
    q = db.query(RoutingRule).filter(
        RoutingRule.company_id == company_id,
        RoutingRule.entity_type == entity_type,
        RoutingRule.is_active == True,
        RoutingRule.trigger.in_([trigger, "both"]),
    )
    if trigger == "on_transition" and transition_id:
        # Include rules scoped to this transition AND rules with no transition scope
        q = q.filter(
            (RoutingRule.trigger_transition_id == transition_id) |
            (RoutingRule.trigger_transition_id == None)
        )
    return q.order_by(RoutingRule.priority).all()


# ── Condition evaluation ──────────────────────────────────────────────────────

def _matches_conditions(entity, conditions: list) -> bool:
    """All conditions must pass (AND logic)."""
    for cond in conditions:
        if not _eval_condition(entity, cond):
            return False
    return True


def _scalar(v) -> str:
    """Normalize a value to a plain string — unwraps str-enum values."""
    import enum
    if isinstance(v, enum.Enum):
        return str(v.value)
    return str(v)


def _eval_condition(entity, cond: dict) -> bool:
    field = cond.get("field", "")
    operator = cond.get("operator", "eq")
    expected = cond.get("value")

    actual = _get_field_value(entity, field)

    if operator == "exists":
        return actual is not None and actual != "" and actual != []
    if operator == "not_exists":
        return actual is None or actual == "" or actual == []
    if actual is None:
        return False

    if operator == "eq":
        return _scalar(actual) == _scalar(expected)
    elif operator == "neq":
        return _scalar(actual) != _scalar(expected)
    elif operator == "in":
        items = expected if isinstance(expected, list) else [expected]
        return _scalar(actual) in [_scalar(i) for i in items]
    elif operator == "not_in":
        items = expected if isinstance(expected, list) else [expected]
        return _scalar(actual) not in [_scalar(i) for i in items]
    elif operator == "contains":
        # For JSONB list fields (tags, labels) or string contains
        if isinstance(actual, list):
            return str(expected) in [str(x) for x in actual]
        return str(expected).lower() in str(actual).lower()
    elif operator == "gte":
        try:
            return float(actual) >= float(expected)
        except (TypeError, ValueError):
            return False
    elif operator == "lte":
        try:
            return float(actual) <= float(expected)
        except (TypeError, ValueError):
            return False

    return False


def _get_field_value(entity, field: str) -> Any:
    """
    Resolve a field path from the entity.
    Supports: direct attributes and "custom_fields.key" dot notation.
    """
    if "." in field:
        parts = field.split(".", 1)
        parent_val = getattr(entity, parts[0], None)
        if isinstance(parent_val, dict):
            return parent_val.get(parts[1])
        return None

    return getattr(entity, field, None)


# ── Action execution ──────────────────────────────────────────────────────────

def _execute_action(db: Session, rule: RoutingRule, company_id: int, entity=None) -> Optional[int]:
    action_type = rule.action_type
    config = rule.action_config or {}

    if action_type == "assign_to_user":
        return config.get("user_id")

    elif action_type == "assign_round_robin":
        return _round_robin(db, rule, config.get("team_id"), company_id, role=config.get("role"))

    elif action_type == "assign_by_skill":
        return _assign_by_skill(
            db,
            company_id,
            skill=config.get("skill"),
            team_id=config.get("team_id"),
            fallback_user_id=config.get("fallback_user_id"),
        )

    elif action_type == "assign_by_node_match":
        return _assign_by_node_match(db, rule, entity, company_id, config)

    elif action_type == "assign_by_department":
        return _assign_by_department(db, rule, entity, company_id, config)

    elif action_type == "assign_by_role":
        return _assign_by_role(db, rule, company_id, config, entity=entity)

    elif action_type == "no_action":
        return None

    return None


def _infer_dept_ids_from_conditions(
    db: Session, rule: RoutingRule, entity, company_id: int
) -> Optional[List[int]]:
    """
    Scan rule conditions for custom_fields.X hierarchy references (eq/in operators).
    Resolve the entity's actual field values to node ancestor IDs, then find
    departments that cover all matched nodes. Returns dept ID list or None if no
    hierarchy conditions exist.
    """
    from app.models.hierarchy import HierarchyType
    conditions = rule.conditions or []

    type_name_to_id = {
        ht.name.lower(): ht.id
        for ht in db.query(HierarchyType).filter(HierarchyType.company_id == company_id).all()
    }

    # First pass: collect all (type_id, code) lookups needed
    lookups: List[tuple] = []
    lookup_order: List[tuple] = []  # preserves order for result mapping
    for cond in conditions:
        field = cond.get("field", "")
        operator = cond.get("operator", "eq")
        if not field.startswith("custom_fields.") or operator not in ("eq", "in"):
            continue
        sub_key = field.split(".", 1)[1].lower()
        type_id = type_name_to_id.get(sub_key)
        if type_id is None:
            continue
        raw_val = _get_field_value(entity, field)
        if not raw_val:
            continue
        lookups.append((type_id, str(raw_val)))
        lookup_order.append((type_id, str(raw_val)))

    if not lookups:
        return None

    # Single query for all needed nodes
    from sqlalchemy import tuple_ as sa_tuple
    node_rows = db.query(HierarchyNode).filter(
        HierarchyNode.company_id == company_id,
        HierarchyNode.is_active == True,
        sa_tuple(HierarchyNode.type_id, HierarchyNode.code).in_(lookups),
    ).all()
    nodes_by_key = {(n.type_id, n.code): n for n in node_rows}

    node_id_sets: List[set] = []
    for type_id, code in lookup_order:
        node = nodes_by_key.get((type_id, code))
        if not node:
            continue
        ancestor_ids = {int(x) for x in node.path.split(".") if x}
        node_id_sets.append(ancestor_ids)

    if not node_id_sets:
        return None

    return dept_svc.find_departments_by_nodes(db, company_id, node_id_sets)


def _assign_by_role(
    db: Session, rule: RoutingRule, company_id: int, config: dict, entity=None
) -> Optional[int]:
    """
    Round-robin among users with the given dept role.
    When the rule has classification/location conditions, scopes to departments
    that handle those hierarchy nodes; otherwise falls back to company-wide.
    """
    from app.models.department import DepartmentUserMembership
    role = config.get("role")
    team_id = config.get("team_id")

    # Try to scope to relevant departments from hierarchy conditions
    dept_ids: Optional[List[int]] = None
    if entity is not None:
        dept_ids = _infer_dept_ids_from_conditions(db, rule, entity, company_id)

    if role:
        q = (
            db.query(DepartmentUserMembership.user_id)
            .join(User, User.id == DepartmentUserMembership.user_id)
            .filter(
                DepartmentUserMembership.company_id == company_id,
                DepartmentUserMembership.role == role,
                User.is_active == True,
            )
        )
        if dept_ids is not None:
            q = q.filter(DepartmentUserMembership.department_id.in_(dept_ids))
        user_ids = [r[0] for r in q.distinct().all()]
    else:
        # Fallback: all active users in company (or scoped depts)
        if dept_ids is not None:
            user_ids = dept_svc.find_users_in_departments(db, company_id, dept_ids, role=None)
        else:
            q = db.query(User.id).filter(User.company_id == company_id, User.is_active == True)
            if team_id:
                q = q.join(TeamMembership, TeamMembership.user_id == User.id).filter(
                    TeamMembership.team_id == team_id
                )
            user_ids = [r[0] for r in q.all()]

    if not user_ids:
        return None

    user_ids = sorted(user_ids)
    state = db.query(RoutingRoundRobinState).filter(RoutingRoundRobinState.rule_id == rule.id).first()
    if state and state.last_assigned_user_id in user_ids:
        idx = user_ids.index(state.last_assigned_user_id)
        next_id = user_ids[(idx + 1) % len(user_ids)]
    else:
        next_id = user_ids[0]

    if state:
        state.last_assigned_user_id = next_id
        state.last_assigned_at = datetime.utcnow()
    else:
        db.add(RoutingRoundRobinState(rule_id=rule.id, last_assigned_user_id=next_id, last_assigned_at=datetime.utcnow()))
    db.flush()
    return next_id


def _round_robin(
    db: Session, rule: RoutingRule, team_id: Optional[int], company_id: int,
    role: Optional[str] = None,
) -> Optional[int]:
    """Pick the next available member in the team (optionally filtered by role) after the last-assigned one."""
    from app.models.department import DepartmentUserMembership
    members = (
        db.query(TeamMembership)
        .join(User, User.id == TeamMembership.user_id)
        .filter(
            TeamMembership.company_id == company_id,
            TeamMembership.is_available == True,
        )
    )
    if team_id:
        members = members.filter(TeamMembership.team_id == team_id)

    if role:
        # Filter to users who have this dept role in at least one department
        role_user_ids = db.query(DepartmentUserMembership.user_id).filter(
            DepartmentUserMembership.company_id == company_id,
            DepartmentUserMembership.role == role,
        ).subquery()
        members = members.filter(TeamMembership.user_id.in_(role_user_ids))

    members = members.order_by(TeamMembership.user_id).all()
    if not members:
        return None

    member_ids = [m.user_id for m in members]

    # Find or create round-robin state
    state = db.query(RoutingRoundRobinState).filter(
        RoutingRoundRobinState.rule_id == rule.id
    ).first()

    next_id: Optional[int] = None

    if state and state.last_assigned_user_id in member_ids:
        idx = member_ids.index(state.last_assigned_user_id)
        next_id = member_ids[(idx + 1) % len(member_ids)]
    else:
        next_id = member_ids[0]

    # Update state
    if state:
        state.last_assigned_user_id = next_id
        state.last_assigned_at = datetime.utcnow()
    else:
        state = RoutingRoundRobinState(
            rule_id=rule.id,
            last_assigned_user_id=next_id,
            last_assigned_at=datetime.utcnow(),
        )
        db.add(state)

    db.flush()
    return next_id


def _assign_by_skill(
    db: Session,
    company_id: int,
    skill: Optional[str],
    team_id: Optional[int],
    fallback_user_id: Optional[int],
) -> Optional[int]:
    """Find the least-loaded available agent who has the required skill."""
    if not skill:
        return fallback_user_id

    q = (
        db.query(TeamMembership)
        .filter(
            TeamMembership.company_id == company_id,
            TeamMembership.is_available == True,
            # PostgreSQL JSONB array contains the skill string
            TeamMembership.skills.op("?")(skill),
        )
    )
    if team_id:
        q = q.filter(TeamMembership.team_id == team_id)

    # Least loaded first
    q = q.order_by(
        TeamMembership.current_session_count.asc(),
        TeamMembership.priority.desc(),
    )

    member = q.first()
    if member:
        return member.user_id

    return fallback_user_id


def _assign_by_node_match(
    db: Session,
    rule: RoutingRule,
    entity,
    company_id: int,
    config: dict,
) -> Optional[int]:
    """
    Assign to a user whose node assignments cover all of the ticket's hierarchy node values.

    config keys:
      node_fields   – list of custom_field names whose values are node codes, e.g. ["location","classification"]
      type_map      – optional dict mapping field name → hierarchy_type_id for code resolution
      team_id       – optional: restrict to users in this team
      ancestor_match– bool (default true): parent nodes in the tree also count as a match
    """
    node_fields: List[str] = config.get("node_fields", [])
    type_map: dict = config.get("type_map", {})
    team_id: Optional[int] = config.get("team_id")
    ancestor_match: bool = config.get("ancestor_match", True)

    if not node_fields:
        return None

    # Step 1: collect all (field, code, type_id) we need, then fetch nodes in one query
    field_lookups = []  # (field_name, code, type_id_or_None)
    for field in node_fields:
        raw_val = _get_field_value(entity, f"custom_fields.{field}") or _get_field_value(entity, field)
        if raw_val:
            field_lookups.append((field, str(raw_val), type_map.get(field)))

    all_required_node_ids: List[set] = []
    if not field_lookups:
        return None

    codes = list({code for _, code, _ in field_lookups})
    node_rows = db.query(HierarchyNode).filter(
        HierarchyNode.company_id == company_id,
        HierarchyNode.code.in_(codes),
        HierarchyNode.is_active == True,
    ).all()
    # Index by (code, type_id) and by code alone for untyped lookups
    nodes_by_code_type = {(n.code, n.type_id): n for n in node_rows}
    nodes_by_code = {n.code: n for n in node_rows}

    for _, code, type_id in field_lookups:
        node = nodes_by_code_type.get((code, type_id)) if type_id else nodes_by_code.get(code)
        if not node:
            continue
        if ancestor_match:
            ancestor_ids = {int(x) for x in node.path.split(".") if x}
        else:
            ancestor_ids = {node.id}
        all_required_node_ids.append(ancestor_ids)

    if not all_required_node_ids:
        return None

    # Step 2: find users who have at least one assignment in EACH field's candidate set
    # We do per-field subqueries and intersect the user_id sets in Python (small sets)
    candidate_sets: List[set] = []
    for node_id_set in all_required_node_ids:
        q = db.query(UserNodeAssignment.user_id).filter(
            UserNodeAssignment.company_id == company_id,
            UserNodeAssignment.node_id.in_(list(node_id_set)),
        )
        if team_id:
            q = q.filter(UserNodeAssignment.team_id == team_id)
        candidate_sets.append({row[0] for row in q.all()})

    # Intersection: user must match all fields
    matched_user_ids = list(candidate_sets[0].intersection(*candidate_sets[1:]))
    if not matched_user_ids:
        return None

    # Step 3: round-robin among matched users via RoutingRoundRobinState
    matched_user_ids.sort()  # stable ordering
    state = db.query(RoutingRoundRobinState).filter(
        RoutingRoundRobinState.rule_id == rule.id
    ).first()

    next_id: Optional[int] = None
    if state and state.last_assigned_user_id in matched_user_ids:
        idx = matched_user_ids.index(state.last_assigned_user_id)
        next_id = matched_user_ids[(idx + 1) % len(matched_user_ids)]
    else:
        next_id = matched_user_ids[0]

    if state:
        state.last_assigned_user_id = next_id
        state.last_assigned_at = datetime.utcnow()
    else:
        db.add(RoutingRoundRobinState(
            rule_id=rule.id,
            last_assigned_user_id=next_id,
            last_assigned_at=datetime.utcnow(),
        ))
    db.flush()
    return next_id


def _assign_by_department(
    db: Session,
    rule: RoutingRule,
    entity,
    company_id: int,
    config: dict,
) -> Optional[int]:
    """
    Two-hop routing: ticket fields → matching departments → user by role within department.

    config keys:
      node_fields    – list of custom_field names whose values are node codes
      type_map       – optional dict mapping field name → hierarchy_type_id
      role           – role to pick from department members (default "agent")
      ancestor_match – bool (default True): parent nodes also count
    """
    node_fields: List[str] = config.get("node_fields", [])
    type_map: dict = config.get("type_map", {})
    role: Optional[str] = config.get("role", "agent")
    ancestor_match: bool = config.get("ancestor_match", True)

    if not node_fields:
        return None

    # Step 1: resolve each field to a set of candidate node IDs (with ancestors)
    node_id_sets: List[set] = []
    for field in node_fields:
        raw_val = _get_field_value(entity, f"custom_fields.{field}") or _get_field_value(entity, field)
        if not raw_val:
            continue
        type_id = type_map.get(field)
        node_q = db.query(HierarchyNode).filter(
            HierarchyNode.company_id == company_id,
            HierarchyNode.code == str(raw_val),
            HierarchyNode.is_active == True,
        )
        if type_id:
            node_q = node_q.filter(HierarchyNode.type_id == type_id)
        node = node_q.first()
        if not node:
            continue
        if ancestor_match:
            ids = {int(x) for x in node.path.split(".") if x}
        else:
            ids = {node.id}
        node_id_sets.append(ids)

    if not node_id_sets:
        return None

    # Step 2: find departments covering ALL fields
    dept_ids = dept_svc.find_departments_by_nodes(db, company_id, node_id_sets)
    if not dept_ids:
        return None

    # Step 3: find users with matching role in those departments
    matched_user_ids = dept_svc.find_users_in_departments(db, company_id, dept_ids, role)
    if not matched_user_ids:
        return None

    # Step 4: round-robin
    matched_user_ids.sort()
    state = db.query(RoutingRoundRobinState).filter(
        RoutingRoundRobinState.rule_id == rule.id
    ).first()

    next_id: Optional[int] = None
    if state and state.last_assigned_user_id in matched_user_ids:
        idx = matched_user_ids.index(state.last_assigned_user_id)
        next_id = matched_user_ids[(idx + 1) % len(matched_user_ids)]
    else:
        next_id = matched_user_ids[0]

    if state:
        state.last_assigned_user_id = next_id
        state.last_assigned_at = datetime.utcnow()
    else:
        db.add(RoutingRoundRobinState(
            rule_id=rule.id,
            last_assigned_user_id=next_id,
            last_assigned_at=datetime.utcnow(),
        ))
    db.flush()
    return next_id


# ── CRUD for RoutingRule ──────────────────────────────────────────────────────

def get_rules(
    db: Session, company_id: int, entity_type: Optional[str] = None
) -> List[RoutingRule]:
    q = db.query(RoutingRule).filter(RoutingRule.company_id == company_id)
    if entity_type:
        q = q.filter(RoutingRule.entity_type == entity_type)
    return q.order_by(RoutingRule.entity_type, RoutingRule.priority).all()


def get_rule(db: Session, rule_id: int, company_id: int) -> Optional[RoutingRule]:
    return db.query(RoutingRule).filter(
        RoutingRule.id == rule_id,
        RoutingRule.company_id == company_id,
    ).first()


def create_rule(db: Session, data, company_id: int) -> RoutingRule:
    conditions = None
    if data.conditions:
        conditions = [c.model_dump() for c in data.conditions]

    rule = RoutingRule(
        company_id=company_id,
        entity_type=data.entity_type,
        name=data.name,
        priority=data.priority,
        trigger=data.trigger,
        trigger_transition_id=data.trigger_transition_id,
        conditions=conditions,
        action_type=data.action_type,
        action_config=data.action_config,
        is_active=data.is_active,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


def update_rule(db: Session, rule_id: int, data, company_id: int) -> RoutingRule:
    from fastapi import HTTPException
    rule = get_rule(db, rule_id, company_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Routing rule not found")

    update_data = data.model_dump(exclude_unset=True)
    if "conditions" in update_data and update_data["conditions"] is not None:
        update_data["conditions"] = [
            c if isinstance(c, dict) else c.model_dump()
            for c in update_data["conditions"]
        ]

    for field, value in update_data.items():
        setattr(rule, field, value)

    db.commit()
    db.refresh(rule)
    return rule


def delete_rule(db: Session, rule_id: int, company_id: int) -> bool:
    from fastapi import HTTPException
    rule = get_rule(db, rule_id, company_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Routing rule not found")
    db.delete(rule)
    db.commit()
    return True


def reorder_rules(
    db: Session, company_id: int, entity_type: str, ordered_ids: List[int]
) -> List[RoutingRule]:
    for pos, rule_id in enumerate(ordered_ids):
        db.query(RoutingRule).filter(
            RoutingRule.id == rule_id,
            RoutingRule.company_id == company_id,
            RoutingRule.entity_type == entity_type,
        ).update({"priority": pos})
    db.commit()
    return get_rules(db, company_id, entity_type)
