from sqlalchemy.orm import Session, joinedload, selectinload
from sqlalchemy import and_, func
from typing import List, Optional
from datetime import datetime
from fastapi import UploadFile

from app.models.ticket import Ticket, TicketComment, TicketAttachment, TicketActivity, TicketLink, TicketProjectMember, ticket_watchers, ticket_co_assignees, TicketActivityAction
from app.models.ticket_project import TicketProject
from app.models.department import DepartmentUserMembership, Department
from app.models.ticket_workflow import TicketWorkflow, TicketStatus, TicketTransition, StatusCategory
from app.models.ticket_issue_type import TicketIssueType
from app.models.ticket_sprint import TicketSprint, SprintStatus
from app.models.drive_item import DriveItem
from app.schemas import ticket as schemas
from app.services import drive_service
import logging
logger = logging.getLogger(__name__)


# ── Default data seeding ──────────────────────────────────────────────────────

DEFAULT_WORKFLOW_STATUSES = [
    {"name": "To Do",       "color": "#94a3b8", "category": StatusCategory.TODO,        "position": 0, "is_default": True},
    {"name": "In Progress", "color": "#3b82f6", "category": StatusCategory.IN_PROGRESS, "position": 1},
    {"name": "In Review",   "color": "#f59e0b", "category": StatusCategory.IN_PROGRESS, "position": 2},
    {"name": "Done",        "color": "#22c55e", "category": StatusCategory.DONE,        "position": 3},
    {"name": "Cancelled",   "color": "#ef4444", "category": StatusCategory.DONE,        "position": 4},
]

DEFAULT_ISSUE_TYPES = [
    {"name": "Bug",      "icon": "bug",          "color": "#ef4444", "is_default": False, "position": 0},
    {"name": "Task",     "icon": "check-square", "color": "#6366f1", "is_default": True,  "position": 1},
    {"name": "Story",    "icon": "bookmark",     "color": "#22c55e", "position": 2},
    {"name": "Epic",     "icon": "zap",          "color": "#f59e0b", "position": 3},
    {"name": "Sub-task", "icon": "git-branch",   "color": "#94a3b8", "position": 4},
]

CRM_WORKFLOWS = {
    "lead": {
        "name": "Lead Workflow",
        "statuses": [
            {"name": "New",         "color": "#94a3b8", "category": StatusCategory.TODO,        "position": 0, "is_default": True},
            {"name": "Contacted",   "color": "#3b82f6", "category": StatusCategory.IN_PROGRESS, "position": 1},
            {"name": "MQL",         "color": "#8b5cf6", "category": StatusCategory.IN_PROGRESS, "position": 2},
            {"name": "SQL",         "color": "#f59e0b", "category": StatusCategory.IN_PROGRESS, "position": 3},
            {"name": "Opportunity", "color": "#ec4899", "category": StatusCategory.IN_PROGRESS, "position": 4},
            {"name": "Won",         "color": "#22c55e", "category": StatusCategory.DONE,        "position": 5},
            {"name": "Lost",        "color": "#ef4444", "category": StatusCategory.DONE,        "position": 6},
        ],
        "transitions": [
            ("Contact",       "New",         "Contacted"),
            ("Qualify (MQL)", "Contacted",   "MQL"),
            ("Qualify (SQL)", "MQL",         "SQL"),
            ("Convert",       "SQL",         "Opportunity"),
            ("Close Won",     "Opportunity", "Won"),
            ("Close Lost",    None,          "Lost"),
            ("Reopen",        "Lost",        "New"),
            ("Reopen",        "Won",         "New"),
        ],
    },
    "deal": {
        "name": "Deal Workflow",
        "statuses": [
            {"name": "Prospecting",  "color": "#94a3b8", "category": StatusCategory.TODO,        "position": 0, "is_default": True},
            {"name": "Qualified",    "color": "#3b82f6", "category": StatusCategory.IN_PROGRESS, "position": 1},
            {"name": "Proposal",     "color": "#8b5cf6", "category": StatusCategory.IN_PROGRESS, "position": 2},
            {"name": "Negotiation",  "color": "#f59e0b", "category": StatusCategory.IN_PROGRESS, "position": 3},
            {"name": "Closed Won",   "color": "#22c55e", "category": StatusCategory.DONE,        "position": 4},
            {"name": "Closed Lost",  "color": "#ef4444", "category": StatusCategory.DONE,        "position": 5},
        ],
        "transitions": [
            ("Qualify",      "Prospecting", "Qualified"),
            ("Propose",      "Qualified",   "Proposal"),
            ("Negotiate",    "Proposal",    "Negotiation"),
            ("Close Won",    "Negotiation", "Closed Won"),
            ("Close Lost",   None,          "Closed Lost"),
            ("Reopen",       "Closed Lost", "Prospecting"),
            ("Reopen",       "Closed Won",  "Prospecting"),
        ],
    },
    "contact": {
        "name": "Contact Workflow",
        "statuses": [
            {"name": "New",        "color": "#94a3b8", "category": StatusCategory.TODO,        "position": 0, "is_default": True},
            {"name": "Subscriber", "color": "#3b82f6", "category": StatusCategory.IN_PROGRESS, "position": 1},
            {"name": "Lead",       "color": "#8b5cf6", "category": StatusCategory.IN_PROGRESS, "position": 2},
            {"name": "MQL",        "color": "#f59e0b", "category": StatusCategory.IN_PROGRESS, "position": 3},
            {"name": "Customer",   "color": "#22c55e", "category": StatusCategory.DONE,        "position": 4},
            {"name": "Churned",    "color": "#ef4444", "category": StatusCategory.DONE,        "position": 5},
        ],
        "transitions": [
            ("Subscribe",  "New",        "Subscriber"),
            ("Qualify",    "Subscriber", "Lead"),
            ("Mark MQL",   "Lead",       "MQL"),
            ("Convert",    "MQL",        "Customer"),
            ("Churn",      None,         "Churned"),
            ("Reactivate", "Churned",    "New"),
        ],
    },
}


def _seed_workflow(db: Session, company_id: int, name: str, entity_type: Optional[str],
                   is_default: bool, statuses_data: list, transitions_data: list) -> TicketWorkflow:
    """Create a workflow with statuses and transitions."""
    wf = TicketWorkflow(company_id=company_id, name=name, is_default=is_default, entity_type=entity_type)
    db.add(wf)
    db.flush()
    for s in statuses_data:
        db.add(TicketStatus(workflow_id=wf.id, company_id=company_id, **s))
    db.flush()
    status_map = {s.name: s.id for s in db.query(TicketStatus).filter(TicketStatus.workflow_id == wf.id).all()}
    for name_, from_name, to_name in transitions_data:
        from_id = status_map.get(from_name) if from_name else None
        to_id = status_map.get(to_name)
        if to_id:
            db.add(TicketTransition(workflow_id=wf.id, name=name_, from_status_id=from_id, to_status_id=to_id))
    return wf


def seed_company_defaults(db: Session, company_id: int):
    """Create default ticket workflow, CRM workflows, and issue types for a company."""
    existing = db.query(TicketWorkflow).filter(
        TicketWorkflow.company_id == company_id,
        TicketWorkflow.is_default == True
    ).first()
    if not existing:
        ticket_wf = _seed_workflow(
            db, company_id, "Default Workflow", entity_type=None, is_default=True,
            statuses_data=DEFAULT_WORKFLOW_STATUSES,
            transitions_data=[
                ("Start",        "To Do",       "In Progress"),
                ("Review",       "In Progress", "In Review"),
                ("Done",         "In Review",   "Done"),
                ("Reopen",       "Done",        "To Do"),
                ("Cancel",       None,          "Cancelled"),
                ("Back to Todo", "In Progress", "To Do"),
            ],
        )

    # Seed CRM workflows if missing
    for entity_type, cfg in CRM_WORKFLOWS.items():
        exists = db.query(TicketWorkflow).filter(
            TicketWorkflow.company_id == company_id,
            TicketWorkflow.entity_type == entity_type,
        ).first()
        if not exists:
            _seed_workflow(
                db, company_id, cfg["name"], entity_type=entity_type, is_default=False,
                statuses_data=cfg["statuses"], transitions_data=cfg["transitions"],
            )

    existing_types = db.query(TicketIssueType).filter(TicketIssueType.company_id == company_id).count()
    if existing_types == 0:
        for t in DEFAULT_ISSUE_TYPES:
            db.add(TicketIssueType(company_id=company_id, **t))

    db.commit()
    return existing


def get_crm_workflow(db: Session, company_id: int, entity_type: str) -> Optional[TicketWorkflow]:
    """Get (or lazily create) the CRM workflow for an entity type."""
    wf = db.query(TicketWorkflow).filter(
        TicketWorkflow.company_id == company_id,
        TicketWorkflow.entity_type == entity_type,
    ).first()
    if not wf and entity_type in CRM_WORKFLOWS:
        cfg = CRM_WORKFLOWS[entity_type]
        wf = _seed_workflow(
            db, company_id, cfg["name"], entity_type=entity_type, is_default=False,
            statuses_data=cfg["statuses"], transitions_data=cfg["transitions"],
        )
        db.commit()
    return wf


def get_workflow_with_details(db: Session, workflow_id: int) -> Optional[TicketWorkflow]:
    return db.query(TicketWorkflow).options(
        selectinload(TicketWorkflow.statuses),
        selectinload(TicketWorkflow.transitions).joinedload(TicketTransition.from_status),
        selectinload(TicketWorkflow.transitions).joinedload(TicketTransition.to_status),
    ).filter(TicketWorkflow.id == workflow_id).first()


def get_available_transitions(db: Session, workflow_id: int, status_id: Optional[int]) -> List[TicketTransition]:
    """Return transitions available from the given status (or from any status if status_id is None)."""
    return db.query(TicketTransition).options(
        joinedload(TicketTransition.to_status),
    ).filter(
        TicketTransition.workflow_id == workflow_id,
        (TicketTransition.from_status_id == status_id) | (TicketTransition.from_status_id == None),
    ).all()


def execute_entity_transition(
    db: Session,
    entity,  # Lead | Deal | Contact — any model with workflow_id + status_id
    transition_id: int,
    data: schemas.TicketTransitionExecute,
    company_id: int,
    user_id: int,
) -> None:
    """Execute a workflow transition on any CRM entity (lead, deal, contact)."""
    transition = db.query(TicketTransition).options(
        joinedload(TicketTransition.to_status),
        joinedload(TicketTransition.from_status),
    ).filter(TicketTransition.id == transition_id).first()

    if not transition:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Transition not found")
    if transition.workflow_id != entity.workflow_id:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Transition does not belong to this entity's workflow")
    if transition.from_status_id and transition.from_status_id != entity.status_id:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Transition not valid from current status")

    # Validate required screen fields
    if transition.screen_fields:
        fv = data.field_values or {}
        for sf in transition.screen_fields:
            if sf.get("required") and sf.get("field") != "comment":
                if not fv.get(sf["field"]):
                    from fastapi import HTTPException
                    raise HTTPException(status_code=422, detail=f"{sf['label']} is required")
        if any(sf.get("required") and sf.get("field") == "comment" for sf in transition.screen_fields):
            if not data.comment:
                from fastapi import HTTPException
                raise HTTPException(status_code=422, detail="Comment is required")

    # Apply status change
    entity.status_id = transition.to_status_id

    # Apply field values — built-in fields + custom fields
    fv = data.field_values or {}
    _BUILTIN_FIELDS = {"assignee_id", "priority", "due_date", "time_estimate"}

    if "assignee_id" in fv and hasattr(entity, "assignee_id"):
        entity.assignee_id = fv["assignee_id"]
    if "priority" in fv and hasattr(entity, "priority"):
        entity.priority = fv["priority"]
    if "due_date" in fv and hasattr(entity, "due_date"):
        entity.due_date = fv["due_date"]
    if "time_estimate" in fv and hasattr(entity, "time_estimate"):
        entity.time_estimate = fv["time_estimate"]

    # Persist validated custom field values into entity.custom_fields
    custom_fv = {k: v for k, v in fv.items() if k not in _BUILTIN_FIELDS}
    if custom_fv:
        from app.services.custom_field_service import validate_custom_field_values
        # Determine entity_type from class name
        entity_type_name = type(entity).__name__.lower()  # "lead", "deal", "contact", "ticket"
        validated = validate_custom_field_values(
            db, company_id, entity_type_name, custom_fv, required_only=True
        )
        existing_cf = dict(entity.custom_fields or {})
        existing_cf.update(validated)
        entity.custom_fields = existing_cf

    # Apply post-actions
    if transition.post_actions:
        assign = transition.post_actions.get("assign_to", {})
        atype = assign.get("type")
        if atype == "reporter" and hasattr(entity, "reporter_id"):
            entity.assignee_id = entity.reporter_id
        elif atype == "unassign" and hasattr(entity, "assignee_id"):
            entity.assignee_id = None
        elif atype == "user":
            uid = assign.get("value")
            if uid and hasattr(entity, "assignee_id"):
                entity.assignee_id = int(uid)
        elif atype == "role":
            from app.models.user import User
            role_user = db.query(User).filter(
                User.company_id == company_id, User.role == assign.get("value")
            ).first()
            if role_user and hasattr(entity, "assignee_id"):
                entity.assignee_id = role_user.id

    # Fire on_transition routing rules
    if hasattr(entity, "assignee_id") and entity.assignee_id is None:
        from app.services.routing_service import evaluate_and_route
        entity_type_name = type(entity).__name__.lower()
        evaluate_and_route(
            db, entity, entity_type_name, company_id,
            trigger="on_transition", transition_id=transition_id
        )

    db.commit()


# ── Projects ──────────────────────────────────────────────────────────────────

def get_projects(db: Session, company_id: int) -> List[TicketProject]:
    return db.query(TicketProject).filter(
        TicketProject.company_id == company_id
    ).options(
        joinedload(TicketProject.default_workflow).selectinload(TicketWorkflow.statuses),
        joinedload(TicketProject.default_workflow).selectinload(TicketWorkflow.transitions),
        selectinload(TicketProject.members).joinedload(TicketProjectMember.user),
    ).order_by(TicketProject.created_at).all()


def get_project(db: Session, project_id: int, company_id: int) -> Optional[TicketProject]:
    return db.query(TicketProject).filter(
        TicketProject.id == project_id,
        TicketProject.company_id == company_id
    ).options(
        joinedload(TicketProject.default_workflow).selectinload(TicketWorkflow.statuses),
        joinedload(TicketProject.default_workflow).selectinload(TicketWorkflow.transitions),
        selectinload(TicketProject.members).joinedload(TicketProjectMember.user),
    ).first()


def _create_workflow_for_project(db: Session, company_id: int, project_name: str) -> TicketWorkflow:
    """Create a fresh workflow named after the project with the default statuses/transitions."""
    workflow = TicketWorkflow(
        company_id=company_id,
        name=f"{project_name} Workflow",
        is_default=False,
    )
    db.add(workflow)
    db.flush()

    for s in DEFAULT_WORKFLOW_STATUSES:
        db.add(TicketStatus(workflow_id=workflow.id, company_id=company_id, **s))
    db.flush()

    statuses = db.query(TicketStatus).filter(TicketStatus.workflow_id == workflow.id).order_by(TicketStatus.position).all()
    status_map = {s.name: s.id for s in statuses}
    transitions = [
        ("Start",        status_map.get("To Do"),       status_map.get("In Progress")),
        ("Review",       status_map.get("In Progress"), status_map.get("In Review")),
        ("Done",         status_map.get("In Review"),   status_map.get("Done")),
        ("Reopen",       status_map.get("Done"),        status_map.get("To Do")),
        ("Cancel",       None,                          status_map.get("Cancelled")),
        ("Back to Todo", status_map.get("In Progress"), status_map.get("To Do")),
    ]
    for name, from_id, to_id in transitions:
        if to_id:
            db.add(TicketTransition(workflow_id=workflow.id, name=name, from_status_id=from_id, to_status_id=to_id))

    return workflow


def create_project(db: Session, project: schemas.TicketProjectCreate, company_id: int, user_id: int) -> TicketProject:
    seed_company_defaults(db, company_id)

    # Use explicitly provided workflow, otherwise create a project-specific one
    workflow_id = project.default_workflow_id
    if not workflow_id:
        wf = _create_workflow_for_project(db, company_id, project.name)
        db.flush()
        workflow_id = wf.id

    db_project = TicketProject(
        **project.model_dump(exclude={"default_workflow_id"}),
        company_id=company_id,
        created_by_id=user_id,
        default_workflow_id=workflow_id,
    )
    db.add(db_project)
    db.flush()
    # Creator is admin member
    db.add(TicketProjectMember(project_id=db_project.id, user_id=user_id, role="admin"))
    db.commit()
    db.refresh(db_project)
    return db_project


def update_project(db: Session, project_id: int, update: schemas.TicketProjectUpdate, company_id: int) -> Optional[TicketProject]:
    p = db.query(TicketProject).filter(TicketProject.id == project_id, TicketProject.company_id == company_id).first()
    if not p:
        return None
    for k, v in update.model_dump(exclude_unset=True).items():
        setattr(p, k, v)
    db.commit()
    db.refresh(p)
    return p


def delete_project(db: Session, project_id: int, company_id: int) -> tuple[bool, Optional[str]]:
    """Returns (success, error_message)."""
    p = db.query(TicketProject).filter(TicketProject.id == project_id, TicketProject.company_id == company_id).first()
    if not p:
        return False, "Project not found"
    ticket_count = db.query(func.count(Ticket.id)).filter(Ticket.project_id == project_id).scalar()
    if ticket_count > 0:
        return False, f"Cannot delete project with {ticket_count} ticket(s). Remove all tickets first."
    db.delete(p)
    db.commit()
    return True, None


# ── Workflows ─────────────────────────────────────────────────────────────────

def get_workflows(db: Session, company_id: int) -> List[TicketWorkflow]:
    return db.query(TicketWorkflow).filter(
        TicketWorkflow.company_id == company_id
    ).options(
        selectinload(TicketWorkflow.statuses),
        selectinload(TicketWorkflow.transitions).joinedload(TicketTransition.from_status),
        selectinload(TicketWorkflow.transitions).joinedload(TicketTransition.to_status),
    ).all()


def get_workflow(db: Session, workflow_id: int, company_id: int) -> Optional[TicketWorkflow]:
    return db.query(TicketWorkflow).filter(
        TicketWorkflow.id == workflow_id,
        TicketWorkflow.company_id == company_id
    ).options(
        selectinload(TicketWorkflow.statuses),
        selectinload(TicketWorkflow.transitions).joinedload(TicketTransition.from_status),
        selectinload(TicketWorkflow.transitions).joinedload(TicketTransition.to_status),
    ).first()


def create_workflow(db: Session, data: schemas.TicketWorkflowCreate, company_id: int) -> TicketWorkflow:
    wf = TicketWorkflow(**data.model_dump(), company_id=company_id)
    if data.is_default:
        db.query(TicketWorkflow).filter(TicketWorkflow.company_id == company_id).update({"is_default": False})
    db.add(wf)
    db.commit()
    db.refresh(wf)
    return wf


def update_workflow(db: Session, workflow_id: int, data: schemas.TicketWorkflowUpdate, company_id: int) -> Optional[TicketWorkflow]:
    wf = db.query(TicketWorkflow).filter(TicketWorkflow.id == workflow_id, TicketWorkflow.company_id == company_id).first()
    if not wf:
        return None
    if data.is_default:
        db.query(TicketWorkflow).filter(TicketWorkflow.company_id == company_id, TicketWorkflow.id != workflow_id).update({"is_default": False})
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(wf, k, v)
    db.commit()
    db.refresh(wf)
    return wf


def delete_workflow(db: Session, workflow_id: int, company_id: int) -> tuple[bool, Optional[str]]:
    """Returns (success, error_message)."""
    wf = db.query(TicketWorkflow).filter(
        TicketWorkflow.id == workflow_id, TicketWorkflow.company_id == company_id
    ).first()
    if not wf:
        return False, "Workflow not found"
    linked = db.query(TicketProject).filter(
        TicketProject.default_workflow_id == workflow_id,
        TicketProject.company_id == company_id,
    ).all()
    if linked:
        names = ", ".join(p.name for p in linked)
        return False, f"Workflow is used by project(s): {names}"
    db.delete(wf)
    db.commit()
    return True, None


def create_status(db: Session, workflow_id: int, data: schemas.TicketStatusCreate, company_id: int) -> TicketStatus:
    if data.is_default:
        db.query(TicketStatus).filter(TicketStatus.workflow_id == workflow_id).update({"is_default": False})
    s = TicketStatus(**data.model_dump(), workflow_id=workflow_id, company_id=company_id)
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


def update_status(db: Session, status_id: int, data: schemas.TicketStatusUpdate, company_id: int) -> Optional[TicketStatus]:
    s = db.query(TicketStatus).filter(TicketStatus.id == status_id, TicketStatus.company_id == company_id).first()
    if not s:
        return None
    if data.is_default:
        db.query(TicketStatus).filter(TicketStatus.workflow_id == s.workflow_id, TicketStatus.id != status_id).update({"is_default": False})
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(s, k, v)
    db.commit()
    db.refresh(s)
    return s


def delete_status(db: Session, status_id: int, company_id: int) -> bool:
    s = db.query(TicketStatus).filter(TicketStatus.id == status_id, TicketStatus.company_id == company_id).first()
    if not s:
        return False
    db.delete(s)
    db.commit()
    return True


def create_transition(db: Session, workflow_id: int, data: schemas.TicketTransitionCreate, company_id: int) -> TicketTransition:
    t = TicketTransition(**data.model_dump(), workflow_id=workflow_id)
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def update_transition(db: Session, transition_id: int, data: schemas.TicketTransitionUpdate, company_id: int) -> Optional[TicketTransition]:
    t = db.query(TicketTransition).join(TicketWorkflow).filter(
        TicketTransition.id == transition_id,
        TicketWorkflow.company_id == company_id
    ).first()
    if not t:
        return None
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(t, k, v)
    db.commit()
    db.refresh(t)
    return t


def delete_transition(db: Session, transition_id: int, company_id: int) -> bool:
    t = db.query(TicketTransition).join(TicketWorkflow).filter(
        TicketTransition.id == transition_id,
        TicketWorkflow.company_id == company_id
    ).first()
    if not t:
        return False
    db.delete(t)
    db.commit()
    return True


# ── Issue Types ───────────────────────────────────────────────────────────────

def get_issue_types(db: Session, company_id: int) -> List[TicketIssueType]:
    return db.query(TicketIssueType).filter(
        TicketIssueType.company_id == company_id
    ).order_by(TicketIssueType.position).all()


def create_issue_type(db: Session, data: schemas.TicketIssueTypeCreate, company_id: int) -> TicketIssueType:
    t = TicketIssueType(**data.model_dump(), company_id=company_id)
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def update_issue_type(db: Session, type_id: int, data: schemas.TicketIssueTypeUpdate, company_id: int) -> Optional[TicketIssueType]:
    t = db.query(TicketIssueType).filter(TicketIssueType.id == type_id, TicketIssueType.company_id == company_id).first()
    if not t:
        return None
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(t, k, v)
    db.commit()
    db.refresh(t)
    return t


def delete_issue_type(db: Session, type_id: int, company_id: int) -> bool:
    t = db.query(TicketIssueType).filter(TicketIssueType.id == type_id, TicketIssueType.company_id == company_id).first()
    if not t:
        return False
    db.delete(t)
    db.commit()
    return True


# ── Tickets ───────────────────────────────────────────────────────────────────

def _ticket_query(db: Session, company_id: int):
    return db.query(Ticket).filter(Ticket.company_id == company_id).options(
        joinedload(Ticket.status),
        joinedload(Ticket.issue_type),
        joinedload(Ticket.project),
        joinedload(Ticket.assignee),
        joinedload(Ticket.reporter),
        selectinload(Ticket.co_assignees),
    )


def get_tickets(
    db: Session,
    company_id: int,
    project_id: Optional[int] = None,
    status_id: Optional[int] = None,
    assignee_id: Optional[int] = None,
    priority: Optional[str] = None,
    search: Optional[str] = None,
    sprint_id: Optional[int] = None,
    no_sprint: Optional[bool] = None,
    contact_id: Optional[int] = None,
    account_id: Optional[int] = None,
    deal_id: Optional[int] = None,
    ticket_number: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
) -> List[Ticket]:
    q = _ticket_query(db, company_id)
    if project_id:
        q = q.filter(Ticket.project_id == project_id)
    if status_id:
        q = q.filter(Ticket.status_id == status_id)
    if assignee_id:
        q = q.filter(Ticket.assignee_id == assignee_id)
    if priority:
        q = q.filter(Ticket.priority == priority)
    if search:
        q = q.filter(Ticket.title.ilike(f"%{search}%"))
    if sprint_id:
        q = q.filter(Ticket.sprint_id == sprint_id)
    if no_sprint:
        q = q.filter(Ticket.sprint_id == None)
    if contact_id:
        q = q.filter(Ticket.contact_id == contact_id)
    if account_id:
        q = q.filter(Ticket.account_id == account_id)
    if deal_id:
        q = q.filter(Ticket.deal_id == deal_id)
    if ticket_number:
        q = q.filter(Ticket.ticket_number == ticket_number)
    return q.order_by(Ticket.position, Ticket.created_at.desc()).offset(skip).limit(limit).all()


def get_ticket(db: Session, ticket_id: int, company_id: int):
    ticket = db.query(Ticket).filter(
        Ticket.id == ticket_id,
        Ticket.company_id == company_id
    ).options(
        # scalar/many-to-one: safe as joinedload (no row multiplication)
        joinedload(Ticket.status),
        joinedload(Ticket.issue_type),
        joinedload(Ticket.project),
        joinedload(Ticket.assignee),
        joinedload(Ticket.reporter),
        joinedload(Ticket.parent).joinedload(Ticket.status),
        joinedload(Ticket.parent).joinedload(Ticket.issue_type),
        # collections: use selectinload to avoid Cartesian product
        selectinload(Ticket.comments).joinedload(TicketComment.author),
        selectinload(Ticket.attachments).joinedload(TicketAttachment.uploaded_by),
        selectinload(Ticket.activities).joinedload(TicketActivity.actor),
        selectinload(Ticket.watchers),
        selectinload(Ticket.co_assignees),
        selectinload(Ticket.source_links).joinedload(TicketLink.target_ticket).joinedload(Ticket.status),
        selectinload(Ticket.target_links).joinedload(TicketLink.source_ticket).joinedload(Ticket.status),
        selectinload(Ticket.sub_tickets).joinedload(Ticket.status),
        selectinload(Ticket.sub_tickets).joinedload(Ticket.issue_type),
    ).first()

    if ticket:
        ticket.user_context = _build_user_context(db, ticket)
    return ticket


def _build_user_context(db: Session, ticket) -> dict:
    """Build {user_id: {job_title, depts: [{name, role}]}} for all users in this ticket."""
    user_ids = set()
    for act in ticket.activities:
        if act.actor_id:
            user_ids.add(act.actor_id)
    for c in ticket.comments:
        if c.author_id:
            user_ids.add(c.author_id)
    for u in ticket.watchers:
        user_ids.add(u.id)
    for u in ticket.co_assignees:
        user_ids.add(u.id)
    if ticket.assignee_id:
        user_ids.add(ticket.assignee_id)
    if ticket.reporter_id:
        user_ids.add(ticket.reporter_id)

    if not user_ids:
        return {}

    rows = (
        db.query(DepartmentUserMembership, Department.name)
        .join(Department, DepartmentUserMembership.department_id == Department.id)
        .filter(DepartmentUserMembership.user_id.in_(user_ids))
        .all()
    )

    context: dict = {}
    for mem, dept_name in rows:
        uid = str(mem.user_id)
        if uid not in context:
            context[uid] = {"depts": []}
        context[uid]["depts"].append({"name": dept_name, "role": mem.role})

    return context


def create_ticket(db: Session, data: schemas.TicketCreate, company_id: int, reporter_id: int) -> Ticket:
    seed_company_defaults(db, company_id)

    project = db.query(TicketProject).filter(
        TicketProject.id == data.project_id,
        TicketProject.company_id == company_id
    ).first()
    if not project:
        raise ValueError("Project not found")

    # Auto-assign default status if not specified
    status_id = data.status_id
    if not status_id and project.default_workflow_id:
        default_status = db.query(TicketStatus).filter(
            TicketStatus.workflow_id == project.default_workflow_id,
            TicketStatus.is_default == True
        ).first()
        if not default_status:
            default_status = db.query(TicketStatus).filter(
                TicketStatus.workflow_id == project.default_workflow_id
            ).order_by(TicketStatus.position).first()
        if default_status:
            status_id = default_status.id

    # Auto-assign default issue type
    issue_type_id = data.issue_type_id
    if not issue_type_id:
        default_type = db.query(TicketIssueType).filter(
            TicketIssueType.company_id == company_id,
            TicketIssueType.is_default == True
        ).first()
        if default_type:
            issue_type_id = default_type.id

    # Increment project ticket counter
    project.ticket_counter += 1
    ticket_number = f"{project.key}-{project.ticket_counter}"

    # Validate and coerce custom fields before persisting
    raw_cf = data.custom_fields or {}
    if raw_cf:
        from app.services.custom_field_service import validate_custom_field_values
        raw_cf = validate_custom_field_values(db, company_id, "ticket", raw_cf)

    ticket_data = data.model_dump(exclude={"status_id", "issue_type_id", "custom_fields"})
    ticket = Ticket(
        **ticket_data,
        custom_fields=raw_cf or None,
        company_id=company_id,
        reporter_id=reporter_id,
        ticket_number=ticket_number,
        status_id=status_id,
        issue_type_id=issue_type_id,
    )
    db.add(ticket)
    db.flush()

    db.add(TicketActivity(
        ticket_id=ticket.id,
        actor_id=reporter_id,
        action=TicketActivityAction.CREATED,
    ))

    # Auto-assign via routing rules (only if no assignee already set)
    if not ticket.assignee_id:
        from app.services.routing_service import evaluate_and_route
        evaluate_and_route(db, ticket, "ticket", company_id, trigger="on_create")

    db.commit()
    db.refresh(ticket)
    return ticket


def update_ticket(db: Session, ticket_id: int, data: schemas.TicketUpdate, company_id: int, actor_id: int) -> Optional[Ticket]:
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id, Ticket.company_id == company_id).first()
    if not ticket:
        return None

    from app.models.user import User as UserModel

    changes = data.model_dump(exclude_unset=True)
    for field, new_val in changes.items():
        old_val = getattr(ticket, field, None)
        if old_val == new_val:
            setattr(ticket, field, new_val)
            continue

        display_old = str(old_val) if old_val is not None else None
        display_new = str(new_val) if new_val is not None else None

        # Resolve human-readable labels for FK fields
        if field == "assignee_id":
            old_user = db.query(UserModel).filter(UserModel.id == old_val).first() if old_val else None
            new_user = db.query(UserModel).filter(UserModel.id == new_val).first() if new_val else None
            display_old = (old_user.full_name or old_user.email) if old_user else None
            display_new = (new_user.full_name or new_user.email) if new_user else None

        # Format datetime values
        if hasattr(old_val, 'strftime'):
            display_old = old_val.strftime('%Y-%m-%d')
        if hasattr(new_val, 'strftime'):
            display_new = new_val.strftime('%Y-%m-%d')

        db.add(TicketActivity(
            ticket_id=ticket_id,
            actor_id=actor_id,
            action=TicketActivityAction.UPDATED,
            field_name=field,
            old_value=display_old,
            new_value=display_new,
        ))
        setattr(ticket, field, new_val)

    db.commit()
    db.refresh(ticket)
    return ticket


def execute_transition(db: Session, ticket_id: int, data: schemas.TicketTransitionExecute, company_id: int, actor_id: int) -> Optional[Ticket]:
    from app.models.user import User as UserModel

    ticket = db.query(Ticket).filter(Ticket.id == ticket_id, Ticket.company_id == company_id).first()
    if not ticket:
        return None

    transition = db.query(TicketTransition).filter(TicketTransition.id == data.transition_id).first()
    if not transition:
        raise ValueError("Transition not found")

    # Validate from_status
    if transition.from_status_id and ticket.status_id != transition.from_status_id:
        raise ValueError("Ticket is not in the required status for this transition")

    # Enforce required screen fields
    screen_fields = transition.screen_fields or []
    field_values = data.field_values or {}
    for sf in screen_fields:
        if isinstance(sf, dict) and sf.get("required"):
            fname = sf.get("field", "")
            # "comment" is handled via data.comment
            if fname == "comment":
                if not data.comment or not data.comment.strip():
                    raise ValueError(f"Field '{sf.get('label', fname)}' is required for this transition")
            elif fname == "attachment":
                # attachments are uploaded separately; skip server-side enforcement
                pass
            else:
                if fname not in field_values or field_values[fname] in (None, ""):
                    raise ValueError(f"Field '{sf.get('label', fname)}' is required for this transition")

    old_status_id = ticket.status_id
    ticket.status_id = transition.to_status_id

    # Apply field_values from screen — built-in + custom fields
    _BUILTIN = {"priority", "assignee_id", "due_date", "time_estimate"}
    custom_fv = {}
    for fname, fval in field_values.items():
        if fname in _BUILTIN and hasattr(ticket, fname):
            if fname == "due_date" and fval:
                try:
                    setattr(ticket, fname, datetime.strptime(fval, "%Y-%m-%d").date())
                except ValueError:
                    logger.exception("Unexpected error")
            elif fname == "time_estimate" and fval is not None:
                ticket.time_estimate = int(fval)
            else:
                setattr(ticket, fname, fval)
        elif fname not in _BUILTIN:
            custom_fv[fname] = fval

    if custom_fv:
        from app.services.custom_field_service import validate_custom_field_values
        validated = validate_custom_field_values(db, company_id, "ticket", custom_fv, required_only=True)
        existing_cf = dict(ticket.custom_fields or {})
        existing_cf.update(validated)
        ticket.custom_fields = existing_cf

    # Mark resolved/closed based on target status category
    new_status = db.query(TicketStatus).filter(TicketStatus.id == transition.to_status_id).first()
    if new_status and new_status.category == StatusCategory.DONE:
        if not ticket.resolved_at:
            ticket.resolved_at = datetime.utcnow()

    # Apply post_actions
    post_actions = transition.post_actions or {}
    assign_to = post_actions.get("assign_to")
    if assign_to:
        assign_type = assign_to.get("type")
        if assign_type == "reporter":
            ticket.assignee_id = ticket.reporter_id
        elif assign_type == "unassign":
            ticket.assignee_id = None
        # "none" means no change — skip intentionally
        elif assign_type == "user":
            user_id = assign_to.get("value")
            if user_id:
                ticket.assignee_id = int(user_id)
        elif assign_type == "role":
            role_name = assign_to.get("value")
            if role_name:
                from app.models.user_role import UserRole
                role_user = db.query(UserModel).join(UserRole).filter(
                    UserModel.company_id == company_id,
                    UserRole.name == role_name,
                ).first()
                if role_user:
                    ticket.assignee_id = role_user.id

    old_status = db.query(TicketStatus).filter(TicketStatus.id == old_status_id).first() if old_status_id else None
    db.add(TicketActivity(
        ticket_id=ticket_id,
        actor_id=actor_id,
        action=TicketActivityAction.TRANSITIONED,
        field_name="status",
        old_value=old_status.name if old_status else None,
        new_value=new_status.name if new_status else str(transition.to_status_id),
        metadata_={
            "transition_id": transition.id,
            "transition_name": transition.name,
            "from_status_color": old_status.color if old_status else None,
            "to_status_color": new_status.color if new_status else None,
        },
    ))

    if data.comment:
        db.add(TicketComment(
            ticket_id=ticket_id,
            author_id=actor_id,
            body=data.comment,
            is_internal=False,
        ))

    # Fire on_transition routing rules if still unassigned
    if not ticket.assignee_id:
        from app.services.routing_service import evaluate_and_route
        evaluate_and_route(
            db, ticket, "ticket", company_id,
            trigger="on_transition", transition_id=data.transition_id
        )

    db.commit()
    db.refresh(ticket)
    return ticket


def get_available_transitions(db: Session, ticket_id: int, company_id: int) -> List[TicketTransition]:
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id, Ticket.company_id == company_id).first()
    if not ticket:
        return []

    project = db.query(TicketProject).filter(TicketProject.id == ticket.project_id).first()
    if not project or not project.default_workflow_id:
        return []

    return db.query(TicketTransition).filter(
        TicketTransition.workflow_id == project.default_workflow_id,
        (TicketTransition.from_status_id == None) | (TicketTransition.from_status_id == ticket.status_id)
    ).options(
        joinedload(TicketTransition.from_status),
        joinedload(TicketTransition.to_status),
    ).all()


def delete_ticket(db: Session, ticket_id: int, company_id: int) -> bool:
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id, Ticket.company_id == company_id).first()
    if not ticket:
        return False
    db.delete(ticket)
    db.commit()
    return True


# ── Comments ──────────────────────────────────────────────────────────────────

def create_comment(db: Session, ticket_id: int, data: schemas.TicketCommentCreate, author_id: int, company_id: int) -> TicketComment:
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id, Ticket.company_id == company_id).first()
    if not ticket:
        raise ValueError("Ticket not found")
    comment = TicketComment(**data.model_dump(), ticket_id=ticket_id, author_id=author_id)
    db.add(comment)
    db.flush()
    db.add(TicketActivity(
        ticket_id=ticket_id,
        actor_id=author_id,
        action=TicketActivityAction.COMMENTED,
        metadata_={"comment_id": comment.id, "is_internal": data.is_internal},
    ))
    db.commit()
    db.refresh(comment)
    return comment


def update_comment(db: Session, comment_id: int, data: schemas.TicketCommentUpdate, author_id: int) -> Optional[TicketComment]:
    comment = db.query(TicketComment).filter(TicketComment.id == comment_id, TicketComment.author_id == author_id).first()
    if not comment:
        return None
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(comment, k, v)
    db.commit()
    db.refresh(comment)
    return comment


def delete_comment(db: Session, comment_id: int, author_id: int) -> bool:
    comment = db.query(TicketComment).filter(TicketComment.id == comment_id, TicketComment.author_id == author_id).first()
    if not comment:
        return False
    db.delete(comment)
    db.commit()
    return True


# ── Attachments ──────────────────────────────────────────────────────────────

def _get_or_create_folder(db: Session, company_id: int, owner_id: int,
                           name: str, parent_id: Optional[int]) -> DriveItem:
    """Find an existing folder by name+parent or create it."""
    existing = db.query(DriveItem).filter(
        DriveItem.company_id == company_id,
        DriveItem.parent_id == parent_id,
        DriveItem.name == name,
        DriveItem.is_folder == True,
    ).first()
    if existing:
        return existing
    item = DriveItem(
        company_id=company_id,
        owner_id=owner_id,
        parent_id=parent_id,
        name=name,
        is_folder=True,
    )
    db.add(item)
    db.flush()
    return item


async def create_attachment(
    db: Session,
    ticket_id: int,
    company_id: int,
    uploader_id: int,
    file: UploadFile,
) -> TicketAttachment:
    ticket = db.query(Ticket).filter(
        Ticket.id == ticket_id, Ticket.company_id == company_id
    ).options(joinedload(Ticket.project)).first()
    if not ticket:
        raise ValueError("Ticket not found")

    # Ensure Drive folder chain: Tickets > ProjectKey > TicketNumber
    root = _get_or_create_folder(db, company_id, uploader_id, "Tickets", None)
    proj_folder = _get_or_create_folder(db, company_id, uploader_id, ticket.project.key, root.id)
    ticket_folder = _get_or_create_folder(db, company_id, uploader_id, ticket.ticket_number, proj_folder.id)
    db.flush()

    # Upload file into the ticket folder via drive_service
    drive_item = await drive_service.upload_file(
        db=db,
        file=file,
        company_id=company_id,
        owner_id=uploader_id,
        parent_id=ticket_folder.id,
    )

    # Generate a long-lived presigned URL (7 days — refresh on demand via Drive)
    file_url = drive_service.get_presigned_url(drive_item, expires_in=604800)

    attachment = TicketAttachment(
        ticket_id=ticket_id,
        uploaded_by_id=uploader_id,
        file_name=drive_item.name,
        file_size=drive_item.file_size,
        mime_type=drive_item.mime_type,
        file_url=file_url,
    )
    db.add(attachment)
    db.flush()
    db.add(TicketActivity(
        ticket_id=ticket_id,
        actor_id=uploader_id,
        action=TicketActivityAction.ATTACHMENT_ADDED,
        metadata_={"file_name": drive_item.name, "drive_item_id": drive_item.id},
    ))
    db.commit()
    db.refresh(attachment)
    return attachment


def delete_attachment(db: Session, attachment_id: int, company_id: int, actor_id: int) -> bool:
    attachment = db.query(TicketAttachment).join(
        Ticket, TicketAttachment.ticket_id == Ticket.id
    ).filter(
        TicketAttachment.id == attachment_id,
        Ticket.company_id == company_id,
    ).first()
    if not attachment:
        return False
    ticket_id = attachment.ticket_id
    file_name = attachment.file_name
    db.delete(attachment)
    db.flush()
    db.add(TicketActivity(
        ticket_id=ticket_id,
        actor_id=actor_id,
        action=TicketActivityAction.ATTACHMENT_REMOVED,
        metadata_={"file_name": file_name},
    ))
    db.commit()
    return True


# ── Links ─────────────────────────────────────────────────────────────────────

def create_link(db: Session, ticket_id: int, data: schemas.TicketLinkCreate, company_id: int, actor_id: int) -> TicketLink:
    link = TicketLink(source_ticket_id=ticket_id, target_ticket_id=data.target_ticket_id, link_type=data.link_type, created_by_id=actor_id)
    db.add(link)
    db.flush()
    db.add(TicketActivity(ticket_id=ticket_id, actor_id=actor_id, action=TicketActivityAction.LINKED, metadata_={"link_id": link.id}))
    db.commit()
    db.refresh(link)
    return link


def delete_link(db: Session, link_id: int, company_id: int) -> bool:
    link = db.query(TicketLink).join(
        Ticket, TicketLink.source_ticket_id == Ticket.id
    ).filter(TicketLink.id == link_id, Ticket.company_id == company_id).first()
    if not link:
        return False
    db.delete(link)
    db.commit()
    return True


# ── Watchers ──────────────────────────────────────────────────────────────────

def add_watcher(db: Session, ticket_id: int, user_id: int, company_id: int) -> bool:
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id, Ticket.company_id == company_id).first()
    if not ticket:
        return False
    db.execute(ticket_watchers.insert().values(ticket_id=ticket_id, user_id=user_id).prefix_with("OR IGNORE"))
    db.commit()
    return True


def remove_watcher(db: Session, ticket_id: int, user_id: int, company_id: int) -> bool:
    db.execute(ticket_watchers.delete().where(
        and_(ticket_watchers.c.ticket_id == ticket_id, ticket_watchers.c.user_id == user_id)
    ))
    db.commit()
    return True


# ── Co-assignees ───────────────────────────────────────────────────────────────

def add_co_assignee(db: Session, ticket_id: int, user_id: int, company_id: int) -> bool:
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id, Ticket.company_id == company_id).first()
    if not ticket:
        return False
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    stmt = pg_insert(ticket_co_assignees).values(
        ticket_id=ticket_id, user_id=user_id
    ).on_conflict_do_nothing()
    db.execute(stmt)
    db.commit()
    return True


def remove_co_assignee(db: Session, ticket_id: int, user_id: int, company_id: int) -> bool:
    db.execute(ticket_co_assignees.delete().where(
        and_(ticket_co_assignees.c.ticket_id == ticket_id, ticket_co_assignees.c.user_id == user_id)
    ))
    db.commit()
    return True


# ── Stats ─────────────────────────────────────────────────────────────────────

def get_stats(db: Session, company_id: int, project_id: Optional[int] = None) -> dict:
    q = db.query(Ticket).filter(Ticket.company_id == company_id)
    if project_id:
        q = q.filter(Ticket.project_id == project_id)

    tickets = q.options(joinedload(Ticket.status), joinedload(Ticket.issue_type)).all()

    by_status: dict = {}
    by_priority: dict = {}
    by_issue_type: dict = {}
    open_count = 0
    resolved_count = 0
    overdue_count = 0
    now = datetime.utcnow()

    for t in tickets:
        status_name = t.status.name if t.status else "Unknown"
        by_status[status_name] = by_status.get(status_name, 0) + 1
        by_priority[t.priority.value] = by_priority.get(t.priority.value, 0) + 1
        type_name = t.issue_type.name if t.issue_type else "Unknown"
        by_issue_type[type_name] = by_issue_type.get(type_name, 0) + 1

        if t.status and t.status.category.value in ("todo", "in_progress"):
            open_count += 1
        if t.resolved_at:
            resolved_count += 1
        if t.due_date and t.due_date < now and not t.resolved_at:
            overdue_count += 1

    return {
        "total": len(tickets),
        "by_status": by_status,
        "by_priority": by_priority,
        "by_issue_type": by_issue_type,
        "open_count": open_count,
        "resolved_count": resolved_count,
        "overdue_count": overdue_count,
    }


# ── Sprint CRUD ───────────────────────────────────────────────────────────────

def list_sprints(db: Session, *, project_id: int, company_id: int) -> List[TicketSprint]:
    return (
        db.query(TicketSprint)
        .filter(TicketSprint.project_id == project_id, TicketSprint.company_id == company_id)
        .order_by(TicketSprint.created_at)
        .all()
    )


def get_sprint(db: Session, *, sprint_id: int, company_id: int) -> Optional[TicketSprint]:
    return db.query(TicketSprint).filter(
        TicketSprint.id == sprint_id, TicketSprint.company_id == company_id
    ).first()


def create_sprint(db: Session, *, project_id: int, company_id: int,
                  data: schemas.TicketSprintCreate) -> TicketSprint:
    sprint = TicketSprint(
        project_id=project_id,
        company_id=company_id,
        name=data.name,
        goal=data.goal,
        start_date=data.start_date,
        end_date=data.end_date,
        status=SprintStatus.FUTURE,
    )
    db.add(sprint)
    db.commit()
    db.refresh(sprint)
    return sprint


def update_sprint(db: Session, *, sprint_id: int, company_id: int,
                  data: schemas.TicketSprintUpdate) -> Optional[TicketSprint]:
    sprint = get_sprint(db, sprint_id=sprint_id, company_id=company_id)
    if not sprint:
        return None
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(sprint, field, value)
    if data.status == schemas.SprintStatusEnum.ACTIVE:
        # only one active sprint per project
        db.query(TicketSprint).filter(
            TicketSprint.project_id == sprint.project_id,
            TicketSprint.company_id == company_id,
            TicketSprint.id != sprint_id,
            TicketSprint.status == SprintStatus.ACTIVE,
        ).update({"status": SprintStatus.FUTURE})
    if data.status == schemas.SprintStatusEnum.COMPLETED and not sprint.completed_at:
        sprint.completed_at = datetime.utcnow()
    sprint.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(sprint)
    return sprint


def delete_sprint(db: Session, *, sprint_id: int, company_id: int) -> bool:
    sprint = get_sprint(db, sprint_id=sprint_id, company_id=company_id)
    if not sprint:
        return False
    # unassign tickets from this sprint
    db.query(Ticket).filter(Ticket.sprint_id == sprint_id).update({"sprint_id": None})
    db.delete(sprint)
    db.commit()
    return True


def add_tickets_to_sprint(db: Session, *, sprint_id: int, ticket_ids: List[int],
                           company_id: int) -> int:
    sprint = get_sprint(db, sprint_id=sprint_id, company_id=company_id)
    if not sprint:
        return 0
    updated = db.query(Ticket).filter(
        Ticket.id.in_(ticket_ids),
        Ticket.company_id == company_id,
    ).update({"sprint_id": sprint_id}, synchronize_session=False)
    db.commit()
    return updated


def remove_ticket_from_sprint(db: Session, *, ticket_id: int, company_id: int) -> bool:
    ticket = db.query(Ticket).filter(
        Ticket.id == ticket_id, Ticket.company_id == company_id
    ).first()
    if not ticket:
        return False
    ticket.sprint_id = None
    db.commit()
    return True
