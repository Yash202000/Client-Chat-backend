import json
from sqlalchemy.orm import Session, joinedload
from app.models import workflow as models_workflow, agent as models_agent
from app.schemas import workflow as schemas_workflow
from app.services import vectorization_service

def get_workflow(db: Session, workflow_id: int):
    return db.query(models_workflow.Workflow).options(
        joinedload(models_workflow.Workflow.agent),
        joinedload(models_workflow.Workflow.versions)
    ).filter(models_workflow.Workflow.id == workflow_id).first()

def get_workflows(db: Session, company_id: int, skip: int = 0, limit: int = 100):
    return db.query(models_workflow.Workflow).options(
        joinedload(models_workflow.Workflow.agent),
        joinedload(models_workflow.Workflow.versions)
    ).join(models_agent.Agent).filter(
        models_agent.Agent.company_id == company_id,
        models_workflow.Workflow.parent_workflow_id == None
    ).offset(skip).limit(limit).all()

def create_workflow(db: Session, workflow: schemas_workflow.WorkflowCreate):
    workflow_data = workflow.dict(exclude_unset=True) # Use exclude_unset to handle optional fields
    
    # Default 'steps' to an empty dict if not provided
    if 'steps' not in workflow_data or workflow_data['steps'] is None:
        workflow_data['steps'] = {}

    # Ensure JSON fields are stored as strings
    for field in ['steps', 'visual_steps']:
        if isinstance(workflow_data.get(field), dict):
            workflow_data[field] = json.dumps(workflow_data[field])
            
    # New workflows are version 1 and active by default
    workflow_data['version'] = 1
    workflow_data['is_active'] = True
    
    db_workflow = models_workflow.Workflow(**workflow_data)
    db.add(db_workflow)
    db.commit()
    db.refresh(db_workflow)
    return db_workflow

def create_new_version(db: Session, parent_workflow_id: int):
    parent_workflow = db.query(models_workflow.Workflow).filter(
        models_workflow.Workflow.id == parent_workflow_id
    ).first()

    if not parent_workflow:
        return None

    # Find the highest existing version number for this workflow family
    latest_version = db.query(models_workflow.Workflow).filter(
        models_workflow.Workflow.parent_workflow_id == parent_workflow.id
    ).order_by(models_workflow.Workflow.version.desc()).first()
    
    new_version_number = (latest_version.version + 1) if latest_version else (parent_workflow.version + 1)

    # Create a new workflow instance for the new version
    new_version = models_workflow.Workflow(
        name=parent_workflow.name,
        description=parent_workflow.description,
        agent_id=parent_workflow.agent_id,
        steps=parent_workflow.steps, # This will be a JSON string
        visual_steps=parent_workflow.visual_steps, # Also a JSON string
        version=new_version_number,
        is_active=False, # New versions are inactive by default
        parent_workflow_id=parent_workflow.id
    )

    db.add(new_version)
    db.commit()
    db.refresh(new_version)
    return new_version

def set_active_version(db: Session, version_id: int):
    new_active_version = db.query(models_workflow.Workflow).filter(
        models_workflow.Workflow.id == version_id
    ).first()

    if not new_active_version:
        return None

    parent_id = new_active_version.parent_workflow_id or new_active_version.id

    # Deactivate all other versions in the same family
    db.query(models_workflow.Workflow).filter(
        (models_workflow.Workflow.id == parent_id) | (models_workflow.Workflow.parent_workflow_id == parent_id),
        models_workflow.Workflow.id != version_id
    ).update({"is_active": False})

    # Activate the selected version
    new_active_version.is_active = True
    db.commit()
    db.refresh(new_active_version)
    
    return new_active_version

def update_workflow(db: Session, workflow_id: int, workflow: schemas_workflow.WorkflowUpdate):
    db_workflow = db.query(models_workflow.Workflow).filter(models_workflow.Workflow.id == workflow_id).first()
    if db_workflow:
        update_data = workflow.dict(exclude_unset=True)
        for key, value in update_data.items():
            if key in ['steps', 'visual_steps'] and isinstance(value, dict):
                setattr(db_workflow, key, json.dumps(value))
            else:
                setattr(db_workflow, key, value)
        db.commit()
        db.refresh(db_workflow)
    return db_workflow

def delete_workflow(db: Session, workflow_id: int):
    db_workflow = db.query(models_workflow.Workflow).filter(models_workflow.Workflow.id == workflow_id).first()
    if db_workflow:
        db.delete(db_workflow)
        db.commit()
        return True
    return False

def find_similar_workflow(db: Session, company_id: int, query: str):
    """
    Finds the most similar ACTIVE workflow based on a query string.
    """
    # Only search against active workflows
    active_workflows = db.query(models_workflow.Workflow).options(
        joinedload(models_workflow.Workflow.agent)
    ).join(models_agent.Agent).filter(
        models_agent.Agent.company_id == company_id,
        models_workflow.Workflow.is_active == True
    ).all()

    if not active_workflows:
        print("DEBUG: No active workflows found for company_id:", company_id)
        return None

    query_embedding = vectorization_service.get_embedding(query)
    
    best_match = None
    highest_similarity = -1

    for workflow in active_workflows:
        workflow_text = f"{workflow.name} {workflow.description or ''}"
        workflow_embedding = vectorization_service.get_embedding(workflow_text)
        
        similarity = vectorization_service.cosine_similarity(query_embedding, workflow_embedding)
        
        if similarity > highest_similarity:
            highest_similarity = similarity
            best_match = workflow
            
    if highest_similarity > 0.2:
        print(f"DEBUG: Best match found: '{best_match.name}' (Version: {best_match.version}) with similarity: {highest_similarity}")
        return get_workflow(db, best_match.id)
    else:
        print(f"DEBUG: No workflow found above similarity threshold (0.2). Highest: {highest_similarity}")
        return None
