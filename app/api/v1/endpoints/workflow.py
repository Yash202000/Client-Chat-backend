from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.dependencies import get_db
from app.schemas import workflow as schemas_workflow
from app.services import workflow_service

router = APIRouter()

@router.post("/", response_model=schemas_workflow.Workflow)
def create_workflow(workflow: schemas_workflow.WorkflowCreate, db: Session = Depends(get_db)):
    return workflow_service.create_workflow(db=db, workflow=workflow)

@router.get("/", response_model=List[schemas_workflow.Workflow])
def read_workflows(company_id: int, skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    workflows = workflow_service.get_workflows(db=db, company_id=company_id, skip=skip, limit=limit)
    return workflows

@router.get("/{workflow_id}", response_model=schemas_workflow.Workflow)
def read_workflow(workflow_id: int, db: Session = Depends(get_db)):
    db_workflow = workflow_service.get_workflow(db=db, workflow_id=workflow_id)
    if db_workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return db_workflow

@router.put("/{workflow_id}", response_model=schemas_workflow.Workflow)
def update_workflow(workflow_id: int, workflow: schemas_workflow.WorkflowUpdate, db: Session = Depends(get_db)):
    db_workflow = workflow_service.update_workflow(db=db, workflow_id=workflow_id, workflow=workflow)
    if db_workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return db_workflow

@router.delete("/{workflow_id}")
def delete_workflow(workflow_id: int, db: Session = Depends(get_db)):
    success = workflow_service.delete_workflow(db=db, workflow_id=workflow_id)
    if not success:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return {"message": "Workflow deleted successfully"}

# --- Versioning Endpoints ---

@router.post("/{workflow_id}/versions", response_model=schemas_workflow.Workflow)
def create_workflow_version(workflow_id: int, db: Session = Depends(get_db)):
    """
    Creates a new, inactive version of an existing workflow.
    """
    new_version = workflow_service.create_new_version(db=db, parent_workflow_id=workflow_id)
    if new_version is None:
        raise HTTPException(status_code=404, detail="Workflow to version not found")
    return new_version

@router.put("/versions/{version_id}/activate", response_model=schemas_workflow.Workflow)
def activate_workflow_version(version_id: int, db: Session = Depends(get_db)):
    """
    Activates a specific workflow version, deactivating all others in its family.
    """
    activated_version = workflow_service.set_active_version(db=db, version_id=version_id)
    if activated_version is None:
        raise HTTPException(status_code=404, detail="Workflow version not found")
    return activated_version
