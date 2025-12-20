from typing import List, Dict, Any, Optional
from datetime import datetime
import json
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session
from pydantic import BaseModel
from app.core.dependencies import get_db, get_current_active_user, require_permission
from app.schemas import workflow as schemas_workflow
from app.services import workflow_service, tool_service
from app.services.workflow_intent_service import WorkflowIntentService
from app.models import user as models_user

router = APIRouter()

# Pydantic models for intent_config management
class IntentConfigUpdate(BaseModel):
    intent_config: Optional[Dict[str, Any]] = None

class TestWorkflowIntentRequest(BaseModel):
    message: str

class TestWorkflowIntentResponse(BaseModel):
    intent_detected: bool
    intent_name: Optional[str] = None
    confidence: Optional[float] = None
    matched_method: Optional[str] = None
    entities: Optional[Dict[str, Any]] = None
    should_auto_trigger: bool = False

class WorkflowImportRequest(BaseModel):
    agent_id: int
    workflow_data: Dict[str, Any]

@router.post("/", response_model=schemas_workflow.Workflow, dependencies=[Depends(require_permission("workflow:create"))])
def create_workflow(workflow: schemas_workflow.WorkflowCreate, db: Session = Depends(get_db), current_user: models_user.User = Depends(get_current_active_user)):
    return workflow_service.create_workflow(db=db, workflow=workflow, company_id=current_user.company_id)

@router.get("/", response_model=List[schemas_workflow.Workflow], dependencies=[Depends(require_permission("workflow:read"))])
def read_workflows(skip: int = 0, limit: int = 100, db: Session = Depends(get_db), current_user: models_user.User = Depends(get_current_active_user)):
    workflows = workflow_service.get_workflows(db=db, company_id=current_user.company_id, skip=skip, limit=limit)
    return workflows

# NOTE: This route MUST be defined before /{workflow_id} routes to avoid path conflicts
@router.get("/subworkflow-usage/all", dependencies=[Depends(require_permission("workflow:read"))])
def get_all_subworkflow_usage(
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Get subworkflow usage information for all workflows.
    Returns a dict mapping workflow_id to list of workflows using it.
    """
    all_workflows = workflow_service.get_workflows(
        db=db,
        company_id=current_user.company_id
    )

    # Build a map of workflow_id -> [workflows using it as subworkflow]
    usage_map = {}

    for wf in all_workflows:
        # Get visual_steps - check active version if parent has none
        visual_steps = wf.visual_steps
        if visual_steps is None and wf.versions:
            active_version = next((v for v in wf.versions if v.is_active), None)
            if active_version:
                visual_steps = active_version.visual_steps

        if visual_steps:
            if isinstance(visual_steps, str):
                try:
                    visual_steps = json.loads(visual_steps)
                except:
                    continue

            nodes = visual_steps.get("nodes", [])
            for node in nodes:
                if node.get("type") == "subworkflow":
                    subworkflow_id = node.get("data", {}).get("subworkflow_id")
                    if subworkflow_id:
                        # Ensure integer for consistent key type
                        subworkflow_id = int(subworkflow_id)
                        if subworkflow_id not in usage_map:
                            usage_map[subworkflow_id] = []
                        usage_map[subworkflow_id].append({
                            "id": wf.id,
                            "name": wf.name
                        })

    return usage_map

@router.get("/{workflow_id}", response_model=schemas_workflow.Workflow, dependencies=[Depends(require_permission("workflow:read"))])
def read_workflow(workflow_id: int, db: Session = Depends(get_db), current_user: models_user.User = Depends(get_current_active_user)):
    db_workflow = workflow_service.get_workflow(db=db, workflow_id=workflow_id, company_id=current_user.company_id)
    if db_workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return db_workflow

@router.get("/{workflow_id}/available-subworkflows", dependencies=[Depends(require_permission("workflow:read"))])
def get_available_subworkflows(
    workflow_id: int,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Get workflows available to be used as subworkflows for the specified workflow.
    Excludes the current workflow and any that would create circular references.
    """
    from app.services.workflow_execution_service import WorkflowExecutionService

    # Get all workflows for the company
    all_workflows = workflow_service.get_workflows(
        db=db,
        company_id=current_user.company_id
    )

    exec_service = WorkflowExecutionService(db)
    available = []

    for wf in all_workflows:
        # Can't call self
        if wf.id == workflow_id:
            continue

        # Check for circular reference
        if exec_service._detect_circular_reference(workflow_id, wf.id, current_user.company_id):
            continue

        available.append({
            "id": wf.id,
            "name": wf.name,
            "description": wf.description,
            "has_triggers": bool(wf.trigger_phrases) or bool(wf.intent_config)
        })

    return available

@router.get("/{workflow_id}/used-by", dependencies=[Depends(require_permission("workflow:read"))])
def get_workflows_using_as_subworkflow(
    workflow_id: int,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Get list of workflows that use this workflow as a subworkflow.
    Only returns results if this workflow version is active.
    """
    # Get the workflow being queried
    workflow = workflow_service.get_workflow(db, workflow_id, current_user.company_id)
    if not workflow:
        return []

    # Only show banner for active versions
    if not workflow.is_active:
        return []

    # Determine the ID to search for (parent ID if this is a version, otherwise own ID)
    search_id = workflow.parent_workflow_id or workflow.id

    all_workflows = workflow_service.get_workflows(
        db=db,
        company_id=current_user.company_id
    )

    using_workflows = []
    for wf in all_workflows:
        if wf.id == search_id:
            continue

        # Get visual_steps - check active version if parent has none
        visual_steps = wf.visual_steps
        if visual_steps is None and wf.versions:
            active_version = next((v for v in wf.versions if v.is_active), None)
            if active_version:
                visual_steps = active_version.visual_steps

        # Check if this workflow contains a subworkflow node referencing search_id
        if visual_steps:
            if isinstance(visual_steps, str):
                try:
                    visual_steps = json.loads(visual_steps)
                except:
                    continue

            nodes = visual_steps.get("nodes", [])
            for node in nodes:
                if node.get("type") == "subworkflow":
                    subworkflow_id = node.get("data", {}).get("subworkflow_id")
                    # Ensure integer comparison (JSON may store as string)
                    if subworkflow_id and int(subworkflow_id) == search_id:
                        using_workflows.append({
                            "id": wf.id,
                            "name": wf.name
                        })
                        break

    return using_workflows

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

# --- Export/Import Endpoints ---

@router.get("/{workflow_id}/export", dependencies=[Depends(require_permission("workflow:read"))])
def export_workflow(workflow_id: int, db: Session = Depends(get_db), current_user: models_user.User = Depends(get_current_active_user)):
    """
    Export a workflow as a downloadable JSON file.
    Includes workflow configuration and lists required tools for validation on import.
    """
    workflow_data = workflow_service.export_workflow(db, workflow_id, current_user.company_id)
    if workflow_data is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    export_data = {
        "export_version": "1.0",
        "exported_at": datetime.utcnow().isoformat(),
        "workflow": {
            "name": workflow_data["name"],
            "description": workflow_data["description"],
            "trigger_phrases": workflow_data["trigger_phrases"],
            "visual_steps": workflow_data["visual_steps"],
            "intent_config": workflow_data["intent_config"]
        },
        "required_tools": workflow_data["required_tools"]
    }

    # Create safe filename
    safe_name = "".join(c if c.isalnum() or c in ('-', '_') else '_' for c in workflow_data["name"])

    return Response(
        content=json.dumps(export_data, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}_workflow.json"'}
    )

@router.post("/import", response_model=schemas_workflow.Workflow, dependencies=[Depends(require_permission("workflow:create"))])
def import_workflow(
    request: WorkflowImportRequest,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Import a workflow from an exported JSON file.
    Validates that required tools exist in the company before creating the workflow.
    """
    result = workflow_service.import_workflow(
        db=db,
        import_data=request.workflow_data,
        agent_id=request.agent_id,
        company_id=current_user.company_id
    )

    if "error" in result:
        if result["error"] == "missing_tools":
            raise HTTPException(
                status_code=400,
                detail=f"Missing required tools in your company: {', '.join(result['missing_tools'])}. Please create these tools first."
            )
        else:
            raise HTTPException(status_code=400, detail=result["error"])

    return result["workflow"]

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

@router.put("/versions/{version_id}/deactivate", response_model=schemas_workflow.Workflow, dependencies=[Depends(require_permission("workflow:update"))])
def deactivate_workflow_version(version_id: int, db: Session = Depends(get_db), current_user: models_user.User = Depends(get_current_active_user)):
    """
    Deactivates a specific workflow version.
    """
    deactivated_version = workflow_service.deactivate_version(db=db, version_id=version_id, company_id=current_user.company_id)
    if deactivated_version is None:
        raise HTTPException(status_code=404, detail="Workflow version not found")
    return deactivated_version

# --- Intent Configuration Endpoints ---

@router.get("/{workflow_id}/intent-config", dependencies=[Depends(require_permission("workflow:read"))])
def get_workflow_intent_config(workflow_id: int, db: Session = Depends(get_db), current_user: models_user.User = Depends(get_current_active_user)):
    """
    Get the intent configuration for a specific workflow.
    """
    workflow = workflow_service.get_workflow(db=db, workflow_id=workflow_id, company_id=current_user.company_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    return {
        "workflow_id": workflow.id,
        "workflow_name": workflow.name,
        "intent_config": workflow.intent_config or {}
    }

@router.put("/{workflow_id}/intent-config", response_model=schemas_workflow.Workflow, dependencies=[Depends(require_permission("workflow:update"))])
def update_workflow_intent_config(
    workflow_id: int,
    config: IntentConfigUpdate,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Update the intent configuration for a workflow.
    This allows configuring trigger intents, entities, and auto-trigger settings.
    """
    from sqlalchemy.orm.attributes import flag_modified
    workflow = workflow_service.get_workflow(db=db, workflow_id=workflow_id, company_id=current_user.company_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Directly update the intent_config on the model (bypass WorkflowUpdate schema)
    workflow.intent_config = config.intent_config
    flag_modified(workflow, 'intent_config')
    
    db.commit()
    db.refresh(workflow)

    return workflow

@router.post("/{workflow_id}/test-intent", response_model=TestWorkflowIntentResponse, dependencies=[Depends(require_permission("workflow:read"))])
async def test_workflow_intent(
    workflow_id: int,
    request: TestWorkflowIntentRequest,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Test intent detection for a workflow with a sample message.
    Returns the detected intent, confidence, and extracted entities.
    """
    workflow = workflow_service.get_workflow(db=db, workflow_id=workflow_id, company_id=current_user.company_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    intent_service = WorkflowIntentService(db)

    # Check if workflow has intents enabled
    if not intent_service.workflow_has_intents_enabled(workflow):
        return TestWorkflowIntentResponse(
            intent_detected=False,
            should_auto_trigger=False
        )

    # Detect intent
    intent_match = await intent_service.detect_intent_for_workflow(
        message=request.message,
        workflow=workflow,
        conversation_id="test_conversation",
        company_id=current_user.company_id
    )

    if intent_match:
        intent_dict, confidence, entities, matched_method = intent_match
        should_auto_trigger = intent_service.should_auto_trigger(workflow, confidence)

        return TestWorkflowIntentResponse(
            intent_detected=True,
            intent_name=intent_dict.get("name"),
            confidence=confidence,
            matched_method=matched_method,
            entities=entities,
            should_auto_trigger=should_auto_trigger
        )

    return TestWorkflowIntentResponse(
        intent_detected=False,
        should_auto_trigger=False
    )

@router.delete("/{workflow_id}/intent-config", response_model=schemas_workflow.Workflow, dependencies=[Depends(require_permission("workflow:update"))])
def delete_workflow_intent_config(
    workflow_id: int,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Remove intent configuration from a workflow.
    """
    workflow = workflow_service.get_workflow(db=db, workflow_id=workflow_id, company_id=current_user.company_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Set intent_config to None
    update_data = schemas_workflow.WorkflowUpdate(intent_config=None)
    updated_workflow = workflow_service.update_workflow(
        db=db,
        workflow_id=workflow_id,
        workflow=update_data,
        company_id=current_user.company_id
    )

    return updated_workflow
