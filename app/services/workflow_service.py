from sqlalchemy.orm import Session
from app.models import workflow as models_workflow, agent as models_agent
from app.schemas import workflow as schemas_workflow
from app.services import vectorization_service

def get_workflow(db: Session, workflow_id: int):
    return db.query(models_workflow.Workflow).filter(models_workflow.Workflow.id == workflow_id).first()

def get_workflows(db: Session, company_id: int, skip: int = 0, limit: int = 100):
    return db.query(models_workflow.Workflow).join(models_agent.Agent).filter(
        models_agent.Agent.company_id == company_id
    ).offset(skip).limit(limit).all()

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

def get_workflow_by_name(db: Session, company_id: int, name: str):
    return db.query(models_workflow.Workflow).join(models_agent.Agent).filter(
        models_agent.Agent.company_id == company_id,
        models_workflow.Workflow.name == name
    ).first()

def find_similar_workflow(db: Session, company_id: int, query: str):
    """
    Finds the most similar workflow based on a query string.
    """
    all_workflows = get_workflows(db, company_id=company_id)
    if not all_workflows:
        return None

    query_embedding = vectorization_service.get_embedding(query)
    
    best_match = None
    highest_similarity = -1

    for workflow in all_workflows:
        # We can use a combination of name and description for the embedding
        workflow_text = f"{workflow.name} {workflow.description}"
        workflow_embedding = vectorization_service.get_embedding(workflow_text)
        
        print(workflow_text, workflow_embedding)
        
        similarity = vectorization_service.cosine_similarity(query_embedding, workflow_embedding)
        
        print(similarity)
        
        if similarity > highest_similarity:
            highest_similarity = similarity
            best_match = workflow
            
    # You might want to set a threshold for similarity
    if highest_similarity > 0.5: # Example threshold
        return best_match
    else:
        return None
