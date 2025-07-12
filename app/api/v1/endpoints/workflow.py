from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.dependencies import get_db
from app.schemas import workflow as schemas_workflow
from app.services import workflow_service

router = APIRouter()

@router.post("/", response_model=schemas_workflow.Workflow)
def create_workflow(workflow: schemas_workflow.WorkflowCreate, db: Session = Depends(get_db)):
    print("create workflow post requst called")
    return workflow_service.create_workflow(db=db, workflow=workflow)

@router.get("/", response_model=List[schemas_workflow.Workflow])
def read_workflows(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    workflows = workflow_service.get_workflows(db=db, skip=skip, limit=limit)
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
