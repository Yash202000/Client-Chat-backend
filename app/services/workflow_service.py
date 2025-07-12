from sqlalchemy.orm import Session
from app.models import workflow as models_workflow
from app.schemas import workflow as schemas_workflow

def get_workflow(db: Session, workflow_id: int):
    return db.query(models_workflow.Workflow).filter(models_workflow.Workflow.id == workflow_id).first()

def get_workflows(db: Session, skip: int = 0, limit: int = 100):
    return db.query(models_workflow.Workflow).offset(skip).limit(limit).all()

def create_workflow(db: Session, workflow: schemas_workflow.WorkflowCreate):
    db_workflow = models_workflow.Workflow(**workflow.dict())
    db.add(db_workflow)
    db.commit()
    db.refresh(db_workflow)
    return db_workflow

def update_workflow(db: Session, workflow_id: int, workflow: schemas_workflow.WorkflowUpdate):
    db_workflow = db.query(models_workflow.Workflow).filter(models_workflow.Workflow.id == workflow_id).first()
    if db_workflow:
        update_data = workflow.dict(exclude_unset=True)
        for key, value in update_data.items():
            setattr(db_workflow, key, value)
        db.commit()
        db.refresh(db_workflow)
    return db_workflow

def delete_workflow(db: Session, workflow_id: int):
    db_workflow = db.query(models_workflow.Workflow).filter(models_workflow.Workflow.id == workflow_id).first()
    if db_workflow:
        db.delete(db_workflow)
        db.commit()
    return db_workflow

def get_workflow_by_name(db: Session, name: str, agent_id: int):
    return db.query(models_workflow.Workflow).filter(
        models_workflow.Workflow.name == name,
        models_workflow.Workflow.agent_id == agent_id # Corrected to filter by agent_id
    ).first()
