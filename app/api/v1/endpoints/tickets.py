from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from sqlalchemy.orm import Session
from typing import List, Optional

from app.core.dependencies import get_db, get_current_active_user, require_permission
from app.models import user as models_user
from app.schemas import ticket as schemas
from app.services import ticket_service

router = APIRouter()


# ── Workflows ─────────────────────────────────────────────────────────────────

@router.get("/workflows", response_model=List[schemas.TicketWorkflowOut],
            dependencies=[Depends(require_permission("ticket:read"))])
def list_workflows(db: Session = Depends(get_db),
                   current_user: models_user.User = Depends(get_current_active_user)):
    ticket_service.seed_company_defaults(db, company_id=current_user.company_id)
    return ticket_service.get_workflows(db, company_id=current_user.company_id)


@router.post("/workflows", response_model=schemas.TicketWorkflowOut,
             dependencies=[Depends(require_permission("ticket:manage"))])
def create_workflow(data: schemas.TicketWorkflowCreate, db: Session = Depends(get_db),
                    current_user: models_user.User = Depends(get_current_active_user)):
    return ticket_service.create_workflow(db, data=data, company_id=current_user.company_id)


@router.get("/workflows/{workflow_id}", response_model=schemas.TicketWorkflowOut,
            dependencies=[Depends(require_permission("ticket:read"))])
def get_workflow(workflow_id: int, db: Session = Depends(get_db),
                 current_user: models_user.User = Depends(get_current_active_user)):
    wf = ticket_service.get_workflow(db, workflow_id=workflow_id, company_id=current_user.company_id)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return wf


@router.put("/workflows/{workflow_id}", response_model=schemas.TicketWorkflowOut,
            dependencies=[Depends(require_permission("ticket:manage"))])
def update_workflow(workflow_id: int, data: schemas.TicketWorkflowUpdate,
                    db: Session = Depends(get_db),
                    current_user: models_user.User = Depends(get_current_active_user)):
    wf = ticket_service.update_workflow(db, workflow_id=workflow_id, data=data, company_id=current_user.company_id)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return wf


@router.delete("/workflows/{workflow_id}",
               dependencies=[Depends(require_permission("ticket:manage"))])
def delete_workflow(workflow_id: int, db: Session = Depends(get_db),
                    current_user: models_user.User = Depends(get_current_active_user)):
    ok, err = ticket_service.delete_workflow(db, workflow_id=workflow_id, company_id=current_user.company_id)
    if not ok:
        raise HTTPException(status_code=400, detail=err)
    return {"ok": True}


@router.post("/workflows/{workflow_id}/statuses", response_model=schemas.TicketStatusOut,
             dependencies=[Depends(require_permission("ticket:manage"))])
def add_status(workflow_id: int, data: schemas.TicketStatusCreate,
               db: Session = Depends(get_db),
               current_user: models_user.User = Depends(get_current_active_user)):
    return ticket_service.create_status(db, workflow_id=workflow_id, data=data, company_id=current_user.company_id)


@router.put("/workflows/statuses/{status_id}", response_model=schemas.TicketStatusOut,
            dependencies=[Depends(require_permission("ticket:manage"))])
def update_status(status_id: int, data: schemas.TicketStatusUpdate,
                  db: Session = Depends(get_db),
                  current_user: models_user.User = Depends(get_current_active_user)):
    s = ticket_service.update_status(db, status_id=status_id, data=data, company_id=current_user.company_id)
    if not s:
        raise HTTPException(status_code=404, detail="Status not found")
    return s


@router.delete("/workflows/statuses/{status_id}",
               dependencies=[Depends(require_permission("ticket:manage"))])
def delete_status(status_id: int, db: Session = Depends(get_db),
                  current_user: models_user.User = Depends(get_current_active_user)):
    if not ticket_service.delete_status(db, status_id=status_id, company_id=current_user.company_id):
        raise HTTPException(status_code=404, detail="Status not found")
    return {"ok": True}


@router.post("/workflows/{workflow_id}/transitions", response_model=schemas.TicketTransitionOut,
             dependencies=[Depends(require_permission("ticket:manage"))])
def add_transition(workflow_id: int, data: schemas.TicketTransitionCreate,
                   db: Session = Depends(get_db),
                   current_user: models_user.User = Depends(get_current_active_user)):
    return ticket_service.create_transition(db, workflow_id=workflow_id, data=data, company_id=current_user.company_id)


@router.put("/workflows/transitions/{transition_id}", response_model=schemas.TicketTransitionOut,
            dependencies=[Depends(require_permission("ticket:manage"))])
def update_transition(transition_id: int, data: schemas.TicketTransitionUpdate,
                      db: Session = Depends(get_db),
                      current_user: models_user.User = Depends(get_current_active_user)):
    t = ticket_service.update_transition(db, transition_id=transition_id, data=data, company_id=current_user.company_id)
    if not t:
        raise HTTPException(status_code=404, detail="Transition not found")
    return t


@router.delete("/workflows/transitions/{transition_id}",
               dependencies=[Depends(require_permission("ticket:manage"))])
def delete_transition(transition_id: int, db: Session = Depends(get_db),
                      current_user: models_user.User = Depends(get_current_active_user)):
    if not ticket_service.delete_transition(db, transition_id=transition_id, company_id=current_user.company_id):
        raise HTTPException(status_code=404, detail="Transition not found")
    return {"ok": True}


# ── Issue Types ───────────────────────────────────────────────────────────────

@router.get("/issue-types", response_model=List[schemas.TicketIssueTypeOut],
            dependencies=[Depends(require_permission("ticket:read"))])
def list_issue_types(db: Session = Depends(get_db),
                     current_user: models_user.User = Depends(get_current_active_user)):
    ticket_service.seed_company_defaults(db, current_user.company_id)
    return ticket_service.get_issue_types(db, company_id=current_user.company_id)


@router.post("/issue-types", response_model=schemas.TicketIssueTypeOut,
             dependencies=[Depends(require_permission("ticket:manage"))])
def create_issue_type(data: schemas.TicketIssueTypeCreate, db: Session = Depends(get_db),
                      current_user: models_user.User = Depends(get_current_active_user)):
    return ticket_service.create_issue_type(db, data=data, company_id=current_user.company_id)


@router.put("/issue-types/{type_id}", response_model=schemas.TicketIssueTypeOut,
            dependencies=[Depends(require_permission("ticket:manage"))])
def update_issue_type(type_id: int, data: schemas.TicketIssueTypeUpdate,
                      db: Session = Depends(get_db),
                      current_user: models_user.User = Depends(get_current_active_user)):
    t = ticket_service.update_issue_type(db, type_id=type_id, data=data, company_id=current_user.company_id)
    if not t:
        raise HTTPException(status_code=404, detail="Issue type not found")
    return t


@router.delete("/issue-types/{type_id}",
               dependencies=[Depends(require_permission("ticket:manage"))])
def delete_issue_type(type_id: int, db: Session = Depends(get_db),
                      current_user: models_user.User = Depends(get_current_active_user)):
    if not ticket_service.delete_issue_type(db, type_id=type_id, company_id=current_user.company_id):
        raise HTTPException(status_code=404, detail="Issue type not found")
    return {"ok": True}


# ── Projects ──────────────────────────────────────────────────────────────────

@router.get("/projects", response_model=List[schemas.TicketProjectOut],
            dependencies=[Depends(require_permission("ticket:read"))])
def list_projects(db: Session = Depends(get_db),
                  current_user: models_user.User = Depends(get_current_active_user)):
    from app.models.ticket import Ticket
    from sqlalchemy import func
    projects = ticket_service.get_projects(db, company_id=current_user.company_id)
    # Annotate open_ticket_count
    from app.models.ticket_workflow import TicketStatus, StatusCategory
    for p in projects:
        open_count = db.query(func.count(Ticket.id)).join(
            TicketStatus, Ticket.status_id == TicketStatus.id
        ).filter(
            Ticket.project_id == p.id,
            TicketStatus.category.in_([StatusCategory.TODO, StatusCategory.IN_PROGRESS])
        ).scalar()
        p.open_ticket_count = open_count or 0
    return projects


@router.post("/projects", response_model=schemas.TicketProjectOut,
             dependencies=[Depends(require_permission("ticket:manage"))])
def create_project(data: schemas.TicketProjectCreate, db: Session = Depends(get_db),
                   current_user: models_user.User = Depends(get_current_active_user)):
    return ticket_service.create_project(db, project=data, company_id=current_user.company_id, user_id=current_user.id)


@router.get("/projects/{project_id}", response_model=schemas.TicketProjectOut,
            dependencies=[Depends(require_permission("ticket:read"))])
def get_project(project_id: int, db: Session = Depends(get_db),
                current_user: models_user.User = Depends(get_current_active_user)):
    p = ticket_service.get_project(db, project_id=project_id, company_id=current_user.company_id)
    if not p:
        raise HTTPException(status_code=404, detail="Project not found")
    return p


@router.put("/projects/{project_id}", response_model=schemas.TicketProjectOut,
            dependencies=[Depends(require_permission("ticket:manage"))])
def update_project(project_id: int, data: schemas.TicketProjectUpdate,
                   db: Session = Depends(get_db),
                   current_user: models_user.User = Depends(get_current_active_user)):
    p = ticket_service.update_project(db, project_id=project_id, update=data, company_id=current_user.company_id)
    if not p:
        raise HTTPException(status_code=404, detail="Project not found")
    return p


@router.delete("/projects/{project_id}",
               dependencies=[Depends(require_permission("ticket:manage"))])
def delete_project(project_id: int, db: Session = Depends(get_db),
                   current_user: models_user.User = Depends(get_current_active_user)):
    ok, err = ticket_service.delete_project(db, project_id=project_id, company_id=current_user.company_id)
    if not ok:
        status = 404 if err == "Project not found" else 400
        raise HTTPException(status_code=status, detail=err)
    return {"ok": True}


# ── Tickets ───────────────────────────────────────────────────────────────────

@router.get("/", response_model=List[schemas.TicketOut],
            dependencies=[Depends(require_permission("ticket:read"))])
def list_tickets(
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
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user),
):
    return ticket_service.get_tickets(
        db, company_id=current_user.company_id,
        project_id=project_id, status_id=status_id,
        assignee_id=assignee_id, priority=priority,
        search=search, sprint_id=sprint_id, no_sprint=no_sprint,
        contact_id=contact_id, account_id=account_id, deal_id=deal_id,
        ticket_number=ticket_number,
        skip=skip, limit=limit,
    )


@router.post("/", response_model=schemas.TicketOut,
             dependencies=[Depends(require_permission("ticket:create"))])
def create_ticket(data: schemas.TicketCreate, db: Session = Depends(get_db),
                  current_user: models_user.User = Depends(get_current_active_user)):
    try:
        return ticket_service.create_ticket(db, data=data, company_id=current_user.company_id, reporter_id=current_user.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/stats", response_model=schemas.TicketStats,
            dependencies=[Depends(require_permission("ticket:read"))])
def get_stats(project_id: Optional[int] = None, db: Session = Depends(get_db),
              current_user: models_user.User = Depends(get_current_active_user)):
    return ticket_service.get_stats(db, company_id=current_user.company_id, project_id=project_id)


@router.get("/my", response_model=List[schemas.TicketOut],
            dependencies=[Depends(require_permission("ticket:read"))])
def my_tickets(skip: int = 0, limit: int = 50, db: Session = Depends(get_db),
               current_user: models_user.User = Depends(get_current_active_user)):
    return ticket_service.get_tickets(db, company_id=current_user.company_id,
                                      assignee_id=current_user.id, skip=skip, limit=limit)


@router.get("/{ticket_id}", response_model=schemas.TicketDetailOut,
            dependencies=[Depends(require_permission("ticket:read"))])
def get_ticket(ticket_id: int, db: Session = Depends(get_db),
               current_user: models_user.User = Depends(get_current_active_user)):
    ticket = ticket_service.get_ticket(db, ticket_id=ticket_id, company_id=current_user.company_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    transitions = ticket_service.get_available_transitions(db, ticket_id=ticket_id, company_id=current_user.company_id)
    ticket.available_transitions = transitions
    ticket.comment_count = len(ticket.comments)
    ticket.attachment_count = len(ticket.attachments)
    return ticket


@router.put("/{ticket_id}", response_model=schemas.TicketOut,
            dependencies=[Depends(require_permission("ticket:update"))])
def update_ticket(ticket_id: int, data: schemas.TicketUpdate,
                  db: Session = Depends(get_db),
                  current_user: models_user.User = Depends(get_current_active_user)):
    ticket = ticket_service.update_ticket(db, ticket_id=ticket_id, data=data,
                                          company_id=current_user.company_id, actor_id=current_user.id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return ticket


@router.delete("/{ticket_id}",
               dependencies=[Depends(require_permission("ticket:delete"))])
def delete_ticket(ticket_id: int, db: Session = Depends(get_db),
                  current_user: models_user.User = Depends(get_current_active_user)):
    if not ticket_service.delete_ticket(db, ticket_id=ticket_id, company_id=current_user.company_id):
        raise HTTPException(status_code=404, detail="Ticket not found")
    return {"ok": True}


@router.post("/{ticket_id}/transition", response_model=schemas.TicketOut,
             dependencies=[Depends(require_permission("ticket:update"))])
def execute_transition(ticket_id: int, data: schemas.TicketTransitionExecute,
                       db: Session = Depends(get_db),
                       current_user: models_user.User = Depends(get_current_active_user)):
    try:
        ticket = ticket_service.execute_transition(db, ticket_id=ticket_id, data=data,
                                                   company_id=current_user.company_id, actor_id=current_user.id)
        if not ticket:
            raise HTTPException(status_code=404, detail="Ticket not found")
        return ticket
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{ticket_id}/transitions", response_model=List[schemas.TicketTransitionOut],
            dependencies=[Depends(require_permission("ticket:read"))])
def get_transitions(ticket_id: int, db: Session = Depends(get_db),
                    current_user: models_user.User = Depends(get_current_active_user)):
    return ticket_service.get_available_transitions(db, ticket_id=ticket_id, company_id=current_user.company_id)


# ── Attachments ──────────────────────────────────────────────────────────────

@router.post("/{ticket_id}/attachments", response_model=schemas.TicketAttachmentOut,
             dependencies=[Depends(require_permission("ticket:update"))])
async def upload_attachment(
    ticket_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user),
):
    try:
        return await ticket_service.create_attachment(
            db, ticket_id=ticket_id, company_id=current_user.company_id,
            uploader_id=current_user.id, file=file,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/{ticket_id}/attachments/{attachment_id}",
               dependencies=[Depends(require_permission("ticket:update"))])
def delete_attachment(ticket_id: int, attachment_id: int,
                      db: Session = Depends(get_db),
                      current_user: models_user.User = Depends(get_current_active_user)):
    if not ticket_service.delete_attachment(
        db, attachment_id=attachment_id, company_id=current_user.company_id, actor_id=current_user.id
    ):
        raise HTTPException(status_code=404, detail="Attachment not found")
    return {"ok": True}


# ── Comments ──────────────────────────────────────────────────────────────────

@router.post("/{ticket_id}/comments", response_model=schemas.TicketCommentOut,
             dependencies=[Depends(require_permission("ticket:create"))])
def add_comment(ticket_id: int, data: schemas.TicketCommentCreate,
                db: Session = Depends(get_db),
                current_user: models_user.User = Depends(get_current_active_user)):
    try:
        return ticket_service.create_comment(db, ticket_id=ticket_id, data=data,
                                             author_id=current_user.id, company_id=current_user.company_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/{ticket_id}/comments/{comment_id}", response_model=schemas.TicketCommentOut,
            dependencies=[Depends(require_permission("ticket:update"))])
def update_comment(ticket_id: int, comment_id: int, data: schemas.TicketCommentUpdate,
                   db: Session = Depends(get_db),
                   current_user: models_user.User = Depends(get_current_active_user)):
    comment = ticket_service.update_comment(db, comment_id=comment_id, data=data, author_id=current_user.id)
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")
    return comment


@router.delete("/{ticket_id}/comments/{comment_id}",
               dependencies=[Depends(require_permission("ticket:update"))])
def delete_comment(ticket_id: int, comment_id: int, db: Session = Depends(get_db),
                   current_user: models_user.User = Depends(get_current_active_user)):
    if not ticket_service.delete_comment(db, comment_id=comment_id, author_id=current_user.id):
        raise HTTPException(status_code=404, detail="Comment not found")
    return {"ok": True}


# ── Links ─────────────────────────────────────────────────────────────────────

@router.post("/{ticket_id}/links", response_model=schemas.TicketLinkOut,
             dependencies=[Depends(require_permission("ticket:update"))])
def create_link(ticket_id: int, data: schemas.TicketLinkCreate,
                db: Session = Depends(get_db),
                current_user: models_user.User = Depends(get_current_active_user)):
    return ticket_service.create_link(db, ticket_id=ticket_id, data=data,
                                      company_id=current_user.company_id, actor_id=current_user.id)


@router.delete("/{ticket_id}/links/{link_id}",
               dependencies=[Depends(require_permission("ticket:update"))])
def delete_link(ticket_id: int, link_id: int, db: Session = Depends(get_db),
                current_user: models_user.User = Depends(get_current_active_user)):
    if not ticket_service.delete_link(db, link_id=link_id, company_id=current_user.company_id):
        raise HTTPException(status_code=404, detail="Link not found")
    return {"ok": True}


# ── Watchers ──────────────────────────────────────────────────────────────────

@router.post("/{ticket_id}/watchers/{user_id}",
             dependencies=[Depends(require_permission("ticket:update"))])
def add_watcher(ticket_id: int, user_id: int, db: Session = Depends(get_db),
                current_user: models_user.User = Depends(get_current_active_user)):
    ticket_service.add_watcher(db, ticket_id=ticket_id, user_id=user_id, company_id=current_user.company_id)
    return {"ok": True}


@router.delete("/{ticket_id}/watchers/{user_id}",
               dependencies=[Depends(require_permission("ticket:update"))])
def remove_watcher(ticket_id: int, user_id: int, db: Session = Depends(get_db),
                   current_user: models_user.User = Depends(get_current_active_user)):
    ticket_service.remove_watcher(db, ticket_id=ticket_id, user_id=user_id, company_id=current_user.company_id)
    return {"ok": True}


@router.post("/{ticket_id}/co-assignees/{user_id}",
             dependencies=[Depends(require_permission("ticket:update"))])
def add_co_assignee(ticket_id: int, user_id: int, db: Session = Depends(get_db),
                    current_user: models_user.User = Depends(get_current_active_user)):
    ok = ticket_service.add_co_assignee(db, ticket_id=ticket_id, user_id=user_id, company_id=current_user.company_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return {"ok": True}


@router.delete("/{ticket_id}/co-assignees/{user_id}",
               dependencies=[Depends(require_permission("ticket:update"))])
def remove_co_assignee(ticket_id: int, user_id: int, db: Session = Depends(get_db),
                       current_user: models_user.User = Depends(get_current_active_user)):
    ticket_service.remove_co_assignee(db, ticket_id=ticket_id, user_id=user_id, company_id=current_user.company_id)
    return {"ok": True}


# ── Sprints ───────────────────────────────────────────────────────────────────

@router.get("/projects/{project_id}/sprints", response_model=List[schemas.TicketSprintOut],
            dependencies=[Depends(require_permission("ticket:read"))])
def list_sprints(project_id: int, db: Session = Depends(get_db),
                 current_user: models_user.User = Depends(get_current_active_user)):
    return ticket_service.list_sprints(db, project_id=project_id, company_id=current_user.company_id)


@router.post("/projects/{project_id}/sprints", response_model=schemas.TicketSprintOut,
             dependencies=[Depends(require_permission("ticket:create"))])
def create_sprint(project_id: int, data: schemas.TicketSprintCreate,
                  db: Session = Depends(get_db),
                  current_user: models_user.User = Depends(get_current_active_user)):
    return ticket_service.create_sprint(db, project_id=project_id, company_id=current_user.company_id, data=data)


@router.get("/sprints/{sprint_id}", response_model=schemas.TicketSprintOut,
            dependencies=[Depends(require_permission("ticket:read"))])
def get_sprint(sprint_id: int, db: Session = Depends(get_db),
               current_user: models_user.User = Depends(get_current_active_user)):
    sprint = ticket_service.get_sprint(db, sprint_id=sprint_id, company_id=current_user.company_id)
    if not sprint:
        raise HTTPException(status_code=404, detail="Sprint not found")
    return sprint


@router.patch("/sprints/{sprint_id}", response_model=schemas.TicketSprintOut,
              dependencies=[Depends(require_permission("ticket:update"))])
def update_sprint(sprint_id: int, data: schemas.TicketSprintUpdate,
                  db: Session = Depends(get_db),
                  current_user: models_user.User = Depends(get_current_active_user)):
    sprint = ticket_service.update_sprint(db, sprint_id=sprint_id, company_id=current_user.company_id, data=data)
    if not sprint:
        raise HTTPException(status_code=404, detail="Sprint not found")
    return sprint


@router.delete("/sprints/{sprint_id}",
               dependencies=[Depends(require_permission("ticket:delete"))])
def delete_sprint(sprint_id: int, db: Session = Depends(get_db),
                  current_user: models_user.User = Depends(get_current_active_user)):
    if not ticket_service.delete_sprint(db, sprint_id=sprint_id, company_id=current_user.company_id):
        raise HTTPException(status_code=404, detail="Sprint not found")
    return {"ok": True}


@router.post("/sprints/{sprint_id}/tickets",
             dependencies=[Depends(require_permission("ticket:update"))])
def add_tickets_to_sprint(sprint_id: int, ticket_ids: List[int],
                          db: Session = Depends(get_db),
                          current_user: models_user.User = Depends(get_current_active_user)):
    count = ticket_service.add_tickets_to_sprint(
        db, sprint_id=sprint_id, ticket_ids=ticket_ids, company_id=current_user.company_id
    )
    return {"updated": count}


@router.delete("/{ticket_id}/sprint",
               dependencies=[Depends(require_permission("ticket:update"))])
def remove_ticket_from_sprint(ticket_id: int, db: Session = Depends(get_db),
                              current_user: models_user.User = Depends(get_current_active_user)):
    ticket_service.remove_ticket_from_sprint(db, ticket_id=ticket_id, company_id=current_user.company_id)
    return {"ok": True}
