import json
from sqlalchemy.orm import Session
from app.models import workflow as models_workflow, agent as models_agent
from app.schemas import workflow as schemas_workflow
from app.services import vectorization_service

def _db_workflow_to_schema(db_workflow: models_workflow.Workflow) -> models_workflow.Workflow:
    """
    Parses the 'steps' JSON string field from the DB model into a dictionary for the Pydantic schema.
    'visual_steps' remains a string as defined in the schema.
    """
    if db_workflow:
        if isinstance(db_workflow.steps, str):
            try:
                db_workflow.steps = json.loads(db_workflow.steps)
            except json.JSONDecodeError:
                # If parsing fails, return an empty dict or handle as an error
                db_workflow.steps = {}
        # visual_steps is expected to be a string in the schema, so no parsing is needed.
    return db_workflow

def get_workflow(db: Session, workflow_id: int):
    db_workflow = db.query(models_workflow.Workflow).filter(models_workflow.Workflow.id == workflow_id).first()
    return _db_workflow_to_schema(db_workflow)

def get_workflows(db: Session, company_id: int, skip: int = 0, limit: int = 100):
    db_workflows = db.query(models_workflow.Workflow).join(models_agent.Agent).filter(
        models_agent.Agent.company_id == company_id
    ).offset(skip).limit(limit).all()
    return [_db_workflow_to_schema(wf) for wf in db_workflows]

def create_workflow(db: Session, workflow: schemas_workflow.WorkflowCreate):
    workflow_data = workflow.dict()
    # Ensure 'steps' is stored as a JSON string if it's a dict
    if isinstance(workflow_data.get('steps'), dict):
        workflow_data['steps'] = json.dumps(workflow_data['steps'])
    # 'visual_steps' is already a string from the frontend, but this ensures it's stored correctly if it's a dict
    if isinstance(workflow_data.get('visual_steps'), dict):
        workflow_data['visual_steps'] = json.dumps(workflow_data['visual_steps'])
        
    db_workflow = models_workflow.Workflow(**workflow_data)
    db.add(db_workflow)
    db.commit()
    db.refresh(db_workflow)
    return _db_workflow_to_schema(db_workflow)

def update_workflow(db: Session, workflow_id: int, workflow: schemas_workflow.WorkflowUpdate):
    db_workflow = db.query(models_workflow.Workflow).filter(models_workflow.Workflow.id == workflow_id).first()
    if db_workflow:
        update_data = workflow.dict(exclude_unset=True)
        for key, value in update_data.items():
            # If the field is 'steps' and the value is a dict, serialize it
            if key == 'steps' and isinstance(value, dict):
                setattr(db_workflow, key, json.dumps(value))
            # 'visual_steps' is sent as a string, so it can be set directly
            elif key == 'visual_steps':
                 setattr(db_workflow, key, value)
            else:
                setattr(db_workflow, key, value)
        db.commit()
        db.refresh(db_workflow)
    return _db_workflow_to_schema(db_workflow)

def delete_workflow(db: Session, workflow_id: int):
    db_workflow = db.query(models_workflow.Workflow).filter(models_workflow.Workflow.id == workflow_id).first()
    if db_workflow:
        db.delete(db_workflow)
        db.commit()
        return True
    return False

def get_workflow_by_name(db: Session, company_id: int, name: str):
    db_workflow = db.query(models_workflow.Workflow).join(models_agent.Agent).filter(
        models_agent.Agent.company_id == company_id,
        models_workflow.Workflow.name == name
    ).first()
    return _db_workflow_to_schema(db_workflow)

def find_similar_workflow(db: Session, company_id: int, query: str):
    """
    Finds the most similar workflow based on a query string.
    """
    all_workflows = get_workflows(db, company_id=company_id)
    if not all_workflows:
        print("DEBUG: No workflows found for company_id:", company_id)
        return None

    query_embedding = vectorization_service.get_embedding(query)
    print("DEBUG: Query:", query)
    print("DEBUG: Query Embedding (first 5 elements):", query_embedding[:5])
    
    best_match = None
    highest_similarity = -1

    for workflow in all_workflows:
        workflow_text = f"{workflow.name} {workflow.description or ''}"
        workflow_embedding = vectorization_service.get_embedding(workflow_text)
        
        print(f"DEBUG: Comparing with Workflow: '{workflow.name}'")
        print("DEBUG: Workflow Text:", workflow_text)
        print("DEBUG: Workflow Embedding (first 5 elements):", workflow_embedding[:5])
        
        similarity = vectorization_service.cosine_similarity(query_embedding, workflow_embedding)
        print("DEBUG: Similarity:", similarity)
        
        if similarity > highest_similarity:
            highest_similarity = similarity
            best_match = workflow
            
    # You might want to set a threshold for similarity
    # The current threshold is 0.5, which might be too high for some cases.
    # Consider adjusting this based on your data and desired behavior.
    if highest_similarity > 0.4: # Lowered threshold to 0.4
        print(f"DEBUG: Best match found: '{best_match.name}' with similarity: {highest_similarity}")
        return best_match
    else:
        print(f"DEBUG: No workflow found above similarity threshold (0.5). Highest: {highest_similarity}")
        return None
