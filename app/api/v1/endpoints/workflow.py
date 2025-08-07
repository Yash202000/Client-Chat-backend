from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.dependencies import get_db, get_current_active_user, require_permission
from app.schemas import workflow as schemas_workflow
from app.services import workflow_service
from app.models import user as models_user

router = APIRouter()

@router.post("/", response_model=schemas_workflow.Workflow, dependencies=[Depends(require_permission("workflow:create"))])
def create_workflow(workflow: schemas_workflow.WorkflowCreate, db: Session = Depends(get_db), current_user: models_user.User = Depends(get_current_active_user)):
    return workflow_service.create_workflow(db=db, workflow=workflow, company_id=current_user.company_id)

@router.get("/", response_model=List[schemas_workflow.Workflow], dependencies=[Depends(require_permission("workflow:read"))])
def read_workflows(skip: int = 0, limit: int = 100, db: Session = Depends(get_db), current_user: models_user.User = Depends(get_current_active_user)):
    workflows = workflow_service.get_workflows(db=db, company_id=current_user.company_id, skip=skip, limit=limit)
    return workflows

@router.get("/{workflow_id}", response_model=schemas_workflow.Workflow, dependencies=[Depends(require_permission("workflow:read"))])
def read_workflow(workflow_id: int, db: Session = Depends(get_db), current_user: models_user.User = Depends(get_current_active_user)):
    db_workflow = workflow_service.get_workflow(db=db, workflow_id=workflow_id, company_id=current_user.company_id)
    if db_workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return db_workflow

@router.put("/{workflow_id}", response_model=schemas_workflow.Workflow, dependencies=[Depends(require_permission("workflow:update"))])
def update_workflow(workflow_id: int, workflow: schemas_workflow.WorkflowUpdate, db: Session = Depends(get_db), current_user: models_user.User = Depends(get_current_active_user)):
    db_workflow = workflow_service.update_workflow(db=db, workflow_id=workflow_id, workflow=workflow, company_id=current_user.company_id)
    if db_workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return db_workflow

@router.delete("/{workflow_id}", dependencies=[Depends(require_permission("workflow:delete"))])
def delete_workflow(workflow_id: int, db: Session = Depends(get_db), current_user: models_user.User = Depends(get_current_active_user)):
    success = workflow_service.delete_workflow(db=db, workflow_id=workflow_id, company_id=current_user.company_id)
    if not success:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return {"message": "Workflow deleted successfully"}

# --- Versioning Endpoints ---

@router.post("/{workflow_id}/versions", response_model=schemas_workflow.Workflow, dependencies=[Depends(require_permission("workflow:update"))])
def create_workflow_version(workflow_id: int, db: Session = Depends(get_db), current_user: models_user.User = Depends(get_current_active_user)):
    """
    Creates a new, inactive version of an existing workflow.
    """
    new_version = workflow_service.create_new_version(db=db, parent_workflow_id=workflow_id, company_id=current_user.company_id)
    if new_version is None:
        raise HTTPException(status_code=404, detail="Workflow to version not found")
    return new_version

@router.put("/versions/{version_id}/activate", response_model=schemas_workflow.Workflow, dependencies=[Depends(require_permission("workflow:update"))])
def activate_workflow_version(version_id: int, db: Session = Depends(get_db), current_user: models_user.User = Depends(get_current_active_user)):
    """
    Activates a specific workflow version, deactivating all others in its family.
    """
    activated_version = workflow_service.set_active_version(db=db, version_id=version_id, company_id=current_user.company_id)
    if activated_version is None:
        raise HTTPException(status_code=404, detail="Workflow version not found")
    return activated_version
