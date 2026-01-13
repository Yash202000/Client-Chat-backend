import json
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.orm.attributes import flag_modified
from app.models import workflow as models_workflow, agent as models_agent
from app.schemas import workflow as schemas_workflow
from app.services import vectorization_service, workflow_trigger_service

def get_workflow(db: Session, workflow_id: int, company_id: int):
    return db.query(models_workflow.Workflow).options(
        joinedload(models_workflow.Workflow.agents),
        joinedload(models_workflow.Workflow.versions)
    ).filter(
        models_workflow.Workflow.id == workflow_id,
        models_workflow.Workflow.company_id == company_id
    ).first()

def get_workflows(db: Session, company_id: int, skip: int = 0, limit: int = 100):
    return db.query(models_workflow.Workflow).options(
        joinedload(models_workflow.Workflow.agents),
        joinedload(models_workflow.Workflow.versions)
    ).filter(
        models_workflow.Workflow.company_id == company_id,
        models_workflow.Workflow.parent_workflow_id == None
    ).offset(skip).limit(limit).all()


def get_workflows_for_agent(db: Session, agent_id: int, company_id: int):
    """Get workflows assigned to a specific agent via many-to-many relationship."""
    from app.models.workflow import agent_workflows
    return db.query(models_workflow.Workflow).join(
        agent_workflows
    ).filter(
        agent_workflows.c.agent_id == agent_id,
        models_workflow.Workflow.company_id == company_id,
        models_workflow.Workflow.is_active == True,
        models_workflow.Workflow.parent_workflow_id == None
    ).all()


def create_workflow(db: Session, workflow: schemas_workflow.WorkflowCreate, company_id: int):
    workflow_data = workflow.model_dump(exclude_unset=True)

    if 'steps' not in workflow_data or workflow_data['steps'] is None:
        workflow_data['steps'] = {}

    visual_steps_data = None
    for field in ['steps', 'visual_steps']:
        if isinstance(workflow_data.get(field), dict):
            if field == 'visual_steps':
                visual_steps_data = workflow_data[field]
            workflow_data[field] = json.dumps(workflow_data[field])

    # Auto-generate description if not provided and visual_steps exist
    if not workflow_data.get('description') and visual_steps_data:
        workflow_data['description'] = generate_workflow_description(visual_steps_data)

    # Extract agent_ids for many-to-many relationship
    agent_ids = workflow_data.pop('agent_ids', [])

    workflow_data['version'] = 1
    workflow_data['is_active'] = True
    workflow_data['company_id'] = company_id

    db_workflow = models_workflow.Workflow(**workflow_data)
    db.add(db_workflow)
    db.flush()  # Get the ID before adding agents

    # Add agents via many-to-many relationship
    if agent_ids:
        agents = db.query(models_agent.Agent).filter(
            models_agent.Agent.id.in_(agent_ids),
            models_agent.Agent.company_id == company_id
        ).all()
        db_workflow.agents = agents

    db.commit()
    db.refresh(db_workflow)

    # Sync workflow triggers if visual_steps exist
    if visual_steps_data:
        workflow_trigger_service.sync_workflow_triggers(
            db=db,
            workflow_id=db_workflow.id,
            company_id=company_id,
            visual_steps=visual_steps_data
        )

    return db_workflow

def create_new_version(db: Session, parent_workflow_id: int, company_id: int):
    parent_workflow = get_workflow(db, parent_workflow_id, company_id)

    if not parent_workflow:
        return None

    latest_version = db.query(models_workflow.Workflow).filter(
        models_workflow.Workflow.parent_workflow_id == parent_workflow.id
    ).order_by(models_workflow.Workflow.version.desc()).first()
    
    new_version_number = (latest_version.version + 1) if latest_version else (parent_workflow.version + 1)

    new_version = models_workflow.Workflow(
        name=parent_workflow.name,
        description=parent_workflow.description,
        steps=parent_workflow.steps,
        visual_steps=parent_workflow.visual_steps,
        version=new_version_number,
        is_active=False,
        parent_workflow_id=parent_workflow.id,
        company_id=company_id
    )

    db.add(new_version)
    db.flush()

    # Copy agents from parent workflow
    if parent_workflow.agents:
        new_version.agents = parent_workflow.agents.copy()

    db.commit()
    db.refresh(new_version)
    return new_version

def set_active_version(db: Session, version_id: int, company_id: int):
    new_active_version = get_workflow(db, version_id, company_id)

    if not new_active_version:
        return None

    parent_id = new_active_version.parent_workflow_id or new_active_version.id

    db.query(models_workflow.Workflow).filter(
        (models_workflow.Workflow.id == parent_id) | (models_workflow.Workflow.parent_workflow_id == parent_id),
        models_workflow.Workflow.id != version_id
    ).update({"is_active": False})

    new_active_version.is_active = True
    db.commit()
    db.refresh(new_active_version)

    return new_active_version

def deactivate_version(db: Session, version_id: int, company_id: int):
    """
    Deactivates a specific workflow version.
    """
    workflow_version = get_workflow(db, version_id, company_id)

    if not workflow_version:
        return None

    workflow_version.is_active = False
    db.commit()
    db.refresh(workflow_version)

    return workflow_version

def update_workflow(db: Session, workflow_id: int, workflow: schemas_workflow.WorkflowUpdate, company_id: int):
    db_workflow = get_workflow(db, workflow_id, company_id)
    if db_workflow:
        update_data = workflow.model_dump(exclude_unset=True)
        visual_steps_updated = False
        visual_steps_data = None

        # Handle agent_ids separately for many-to-many
        agent_ids = update_data.pop('agent_ids', None)

        for key, value in update_data.items():
            if key in ['steps', 'visual_steps'] and isinstance(value, dict):
                setattr(db_workflow, key, json.dumps(value))
                if key == 'visual_steps':
                    visual_steps_updated = True
                    visual_steps_data = value
            else:
                setattr(db_workflow, key, value)
                # Flag JSONB columns as modified so SQLAlchemy detects the change
                if key == 'intent_config':
                    flag_modified(db_workflow, 'intent_config')

        # Update agents via many-to-many relationship
        if agent_ids is not None:
            agents = db.query(models_agent.Agent).filter(
                models_agent.Agent.id.in_(agent_ids),
                models_agent.Agent.company_id == company_id
            ).all() if agent_ids else []
            db_workflow.agents = agents

        # Auto-generate description if empty and visual_steps were updated
        if visual_steps_updated and visual_steps_data and not db_workflow.description:
            db_workflow.description = generate_workflow_description(visual_steps_data)

        db.commit()
        db.refresh(db_workflow)

        # Sync workflow triggers if visual_steps were updated
        if visual_steps_updated and visual_steps_data:
            workflow_trigger_service.sync_workflow_triggers(
                db=db,
                workflow_id=workflow_id,
                company_id=company_id,
                visual_steps=visual_steps_data
            )

    return db_workflow

def delete_workflow(db: Session, workflow_id: int, company_id: int):
    db_workflow = get_workflow(db, workflow_id, company_id)
    if db_workflow:
        db.delete(db_workflow)
        db.commit()
        return True
    return False

def _parse_json_field(value, default):
    """Helper to parse potentially double-encoded JSON fields."""
    if value is None:
        return default
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            # Check if still a string (double-encoded)
            if isinstance(parsed, str):
                parsed = json.loads(parsed)
            return parsed
        except json.JSONDecodeError:
            return default
    return value  # Already a dict


def _extract_action(prompt_text: str) -> str:
    """Extract action verb/purpose from prompt text."""
    prompt_lower = prompt_text.lower()
    if 'analyze' in prompt_lower:
        return 'analyze user input'
    elif 'classify' in prompt_lower:
        return 'classify the request'
    elif 'qualify' in prompt_lower:
        return 'qualify leads'
    elif 'support' in prompt_lower:
        return 'provide support'
    elif 'summarize' in prompt_lower:
        return 'summarize information'
    elif 'extract' in prompt_lower:
        return 'extract information'
    elif 'generate' in prompt_lower:
        return 'generate responses'
    elif 'answer' in prompt_lower:
        return 'answer questions'
    elif 'recommend' in prompt_lower:
        return 'make recommendations'
    elif 'translate' in prompt_lower:
        return 'translate content'
    elif 'schedule' in prompt_lower:
        return 'handle scheduling'
    elif 'book' in prompt_lower:
        return 'handle bookings'
    elif 'order' in prompt_lower:
        return 'process orders'
    else:
        return 'process the request'


def generate_workflow_description(visual_steps) -> str:
    """
    Generate concise workflow description from visual_steps for LLM context.

    Args:
        visual_steps: Dict or JSON string containing nodes and edges

    Returns:
        Concise description string describing what the workflow does
    """
    # Parse if string
    if isinstance(visual_steps, str):
        try:
            visual_steps = json.loads(visual_steps)
        except json.JSONDecodeError:
            return ""

    if not visual_steps or 'nodes' not in visual_steps:
        return ""

    nodes = visual_steps.get('nodes', [])
    if not nodes:
        return ""

    descriptions = []

    for node in nodes:
        node_type = node.get('type', '')
        data = node.get('data', {})

        if node_type == 'llm':
            # Extract purpose from prompt
            prompt = data.get('prompt', '')
            if prompt:
                first_line = prompt.split('\n')[0][:100]
                descriptions.append(f"uses AI to {_extract_action(first_line)}")

        elif node_type == 'response':
            output = data.get('output_value', '')
            if output and not output.startswith('{{'):
                # Get meaningful text, not just variables
                clean = output.split('{{')[0].strip()[:50]
                if clean:
                    descriptions.append(f"responds with \"{clean}...\"")

        elif node_type == 'listen':
            var_name = data.get('variable_name', '')
            if var_name:
                readable = var_name.replace('_', ' ')
                descriptions.append(f"collects {readable}")

        elif node_type == 'tool':
            tool_name = data.get('tool_name') or data.get('tool') or data.get('name', '')
            if tool_name:
                descriptions.append(f"executes {tool_name.replace('_', ' ')} tool")

        elif node_type == 'question_classifier':
            classes = data.get('classes', [])
            if classes:
                class_names = [c.get('name', '') for c in classes[:3] if c.get('name')]
                if class_names:
                    descriptions.append(f"classifies into {', '.join(class_names)}")

        elif node_type == 'condition':
            var = data.get('variable', '')
            if var:
                var_name = var.replace('{{context.', '').replace('}}', '').replace('_', ' ')
                descriptions.append(f"checks {var_name}")

        elif node_type == 'http_request':
            method = data.get('method', 'GET')
            descriptions.append(f"makes {method} API call")

        elif node_type == 'knowledge':
            descriptions.append("searches knowledge base")

        elif node_type == 'form':
            fields = data.get('params', {}).get('fields', [])
            if fields:
                field_names = [f.get('name', '') for f in fields[:2] if f.get('name')]
                if field_names:
                    descriptions.append(f"collects {', '.join(field_names)} via form")

        elif node_type == 'subworkflow':
            descriptions.append("runs sub-workflow")

        elif node_type.startswith('trigger_'):
            channel = node_type.replace('trigger_', '').replace('_', ' ')
            descriptions.append(f"triggered from {channel}")

    # Remove duplicates while preserving order
    seen = set()
    unique = []
    for d in descriptions:
        if d not in seen:
            seen.add(d)
            unique.append(d)

    if not unique:
        return ""

    # Build final description
    if len(unique) == 1:
        return f"Workflow that {unique[0]}."
    else:
        return f"Workflow that {', '.join(unique[:-1])}, and {unique[-1]}."

def export_workflow(db: Session, workflow_id: int, company_id: int) -> dict:
    """
    Export a workflow as a dictionary suitable for JSON export.
    Handles double-encoded JSON fields from storage.
    """
    workflow = get_workflow(db, workflow_id, company_id)
    if not workflow:
        return None

    # Debug: Log what we're actually exporting
    print(f"DEBUG export: id={workflow_id}, name={workflow.name}, visual_steps is {'None' if workflow.visual_steps is None else 'present'}")
    if workflow.visual_steps:
        print(f"DEBUG export: visual_steps type={type(workflow.visual_steps)}, len={len(str(workflow.visual_steps))}")

    # If this is a parent workflow with no visual_steps, try to use the active version instead
    if workflow.visual_steps is None and workflow.versions:
        active_version = next((v for v in workflow.versions if v.is_active), None)
        if active_version and active_version.visual_steps:
            print(f"DEBUG export: Using active version {active_version.id} instead of parent {workflow_id}")
            workflow = active_version

    visual_steps = _parse_json_field(workflow.visual_steps, {"nodes": [], "edges": []})
    intent_config = _parse_json_field(workflow.intent_config, {})

    # Extract tool names from nodes
    tool_names = []
    for node in visual_steps.get("nodes", []):
        if node.get("type") == "tool":
            tool_name = node.get("data", {}).get("tool_name") or node.get("data", {}).get("tool")
            if tool_name:
                tool_names.append(tool_name)

    return {
        "name": workflow.name,
        "description": workflow.description,
        "trigger_phrases": workflow.trigger_phrases or [],
        "visual_steps": visual_steps,
        "intent_config": intent_config,
        "required_tools": list(set(tool_names))
    }

def import_workflow(db: Session, import_data: dict, agent_id: int, company_id: int) -> dict:
    """
    Import a workflow from exported JSON data.
    Returns dict with 'workflow' on success or 'error' and 'missing_tools' on failure.
    """
    from app.services import tool_service

    # Validate export version
    export_version = import_data.get("export_version")
    if export_version != "1.0":
        return {"error": f"Unsupported export version: {export_version}. Expected 1.0"}

    workflow_data = import_data.get("workflow", {})
    required_tools = import_data.get("required_tools", [])

    # Validate required tools exist in company (skip builtin tools)
    missing_tools = []
    for tool_name in required_tools:
        # Check if it's a company tool
        tool = tool_service.get_tool_by_name(db, tool_name, company_id)
        if not tool:
            # Also check for builtin tools (company_id is None)
            builtin_tool = tool_service.get_tool_by_name(db, tool_name, None)
            if not builtin_tool:
                missing_tools.append(tool_name)

    if missing_tools:
        return {"error": "missing_tools", "missing_tools": missing_tools}

    # Create workflow with imported data
    new_workflow = schemas_workflow.WorkflowCreate(
        name=f"{workflow_data.get('name', 'Imported Workflow')} (Imported)",
        description=workflow_data.get("description"),
        agent_ids=[agent_id],  # Many-to-many: assign to the specified agent
        trigger_phrases=workflow_data.get("trigger_phrases", []),
        visual_steps=workflow_data.get("visual_steps"),
        intent_config=workflow_data.get("intent_config")
    )

    created_workflow = create_workflow(db=db, workflow=new_workflow, company_id=company_id)
    return {"workflow": created_workflow}

def find_similar_workflow(db: Session, company_id: int, query: str, agent_id: int = None):
    """
    Finds the most similar ACTIVE workflow assigned to the specified agent.
    First, it checks for an exact match in the trigger_phrases.
    If no exact match is found, it falls back to a semantic similarity search.

    Args:
        agent_id: If provided, only returns workflows assigned to this agent.
                  If None, returns workflows that have at least one agent assigned.
    """
    from app.models.workflow import agent_workflows
    from sqlalchemy import distinct

    # Build query to get workflow IDs that have agent assignments
    # Use distinct on workflow ID to avoid duplicates from many-to-many join
    id_query = db.query(distinct(models_workflow.Workflow.id)).join(
        agent_workflows
    ).filter(
        models_workflow.Workflow.company_id == company_id,
        models_workflow.Workflow.is_active == True,
        models_workflow.Workflow.parent_workflow_id == None  # Only root workflows
    )

    # If agent_id is specified, filter to workflows assigned to that agent
    if agent_id:
        id_query = id_query.filter(agent_workflows.c.agent_id == agent_id)

    workflow_ids = [row[0] for row in id_query.all()]

    if not workflow_ids:
        print(f"DEBUG: No active workflows found for company_id: {company_id}, agent_id: {agent_id}")
        return None

    # Fetch full workflow objects
    active_workflows = db.query(models_workflow.Workflow).filter(
        models_workflow.Workflow.id.in_(workflow_ids)
    ).all()

    # 1. Check for an exact match in trigger phrases (case-insensitive)
    for workflow in active_workflows:
        if workflow.trigger_phrases:
            # Ensure trigger_phrases is a list
            phrases = workflow.trigger_phrases if isinstance(workflow.trigger_phrases, list) else []
            if any(phrase.lower() == query.lower() for phrase in phrases):
                print(f"DEBUG: Found direct match for query '{query}' in workflow '{workflow.name}'")
                return get_workflow(db, workflow.id, company_id)

    # 2. If no direct match, fall back to similarity search
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
            
    # Adjust the threshold as needed (0.75 = high confidence matches only)
    SIMILARITY_THRESHOLD = 0.75
    if highest_similarity > SIMILARITY_THRESHOLD:
        print(f"DEBUG: Best match found: '{best_match.name}' (Version: {best_match.version}) with similarity: {highest_similarity}")
        return get_workflow(db, best_match.id, company_id)
    else:
        print(f"DEBUG: No workflow found above similarity threshold ({SIMILARITY_THRESHOLD}). Highest: {highest_similarity}")
        return None
