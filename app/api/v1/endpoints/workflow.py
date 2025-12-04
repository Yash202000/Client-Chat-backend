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

# --- Export/Import Endpoints ---

@router.get("/{workflow_id}/export", dependencies=[Depends(require_permission("workflow:read"))])
def export_workflow(workflow_id: int, db: Session = Depends(get_db), current_user: models_user.User = Depends(get_current_active_user)):
    """
    Export a workflow as a downloadable JSON file.
    Includes workflow configuration and lists required tools for validation on import.
    """
    workflow = workflow_service.get_workflow(db=db, workflow_id=workflow_id, company_id=current_user.company_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Parse visual_steps if it's a string
    visual_steps = workflow.visual_steps
    if isinstance(visual_steps, str):
        try:
            visual_steps = json.loads(visual_steps)
        except json.JSONDecodeError:
            visual_steps = {"nodes": [], "edges": []}

    # Extract tool names from nodes for import validation
    tool_names = []
    if visual_steps:
        for node in visual_steps.get("nodes", []):
            if node.get("type") == "tool":
                tool_name = node.get("data", {}).get("tool_name") or node.get("data", {}).get("tool")
                if tool_name:
                    tool_names.append(tool_name)

    # Parse intent_config if it's a string
    intent_config = workflow.intent_config
    if isinstance(intent_config, str):
        try:
            intent_config = json.loads(intent_config)
        except json.JSONDecodeError:
            intent_config = None

    export_data = {
        "export_version": "1.0",
        "exported_at": datetime.utcnow().isoformat(),
        "workflow": {
            "name": workflow.name,
            "description": workflow.description,
            "trigger_phrases": workflow.trigger_phrases or [],
            "visual_steps": visual_steps,
            "intent_config": intent_config
        },
        "required_tools": list(set(tool_names))
    }

    # Create safe filename
    safe_name = "".join(c if c.isalnum() or c in ('-', '_') else '_' for c in workflow.name)

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
    data = request.workflow_data

    # Validate export version
    export_version = data.get("export_version")
    if export_version != "1.0":
        raise HTTPException(status_code=400, detail=f"Unsupported export version: {export_version}. Expected 1.0")

    workflow_data = data.get("workflow", {})
    required_tools = data.get("required_tools", [])

    # Validate required tools exist in company (skip builtin tools)
    missing_tools = []
    for tool_name in required_tools:
        # Check if it's a builtin tool (they don't have company_id)
        tool = tool_service.get_tool_by_name(db, tool_name, current_user.company_id)
        if not tool:
            # Also check for builtin tools (company_id is None)
            builtin_tool = tool_service.get_tool_by_name(db, tool_name, None)
            if not builtin_tool:
                missing_tools.append(tool_name)

    if missing_tools:
        raise HTTPException(
            status_code=400,
            detail=f"Missing required tools in your company: {', '.join(missing_tools)}. Please create these tools first."
        )

    # Create workflow with imported data
    new_workflow = schemas_workflow.WorkflowCreate(
        name=f"{workflow_data.get('name', 'Imported Workflow')} (Imported)",
        description=workflow_data.get("description"),
        agent_id=request.agent_id,
        trigger_phrases=workflow_data.get("trigger_phrases", []),
        visual_steps=workflow_data.get("visual_steps"),
        intent_config=workflow_data.get("intent_config")
    )

    return workflow_service.create_workflow(db=db, workflow=new_workflow, company_id=current_user.company_id)

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
    workflow = workflow_service.get_workflow(db=db, workflow_id=workflow_id, company_id=current_user.company_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Update the workflow with new intent_config
    update_data = schemas_workflow.WorkflowUpdate(intent_config=config.intent_config)
    updated_workflow = workflow_service.update_workflow(
        db=db,
        workflow_id=workflow_id,
        workflow=update_data,
        company_id=current_user.company_id
    )

    return updated_workflow

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
