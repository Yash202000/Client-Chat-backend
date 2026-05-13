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
from app.services.workflow_ai_service import workflow_ai_chat
from app.services.workflow_simulation_service import simulate_workflow
from app.models import user as models_user
import logging
logger = logging.getLogger(__name__)

router = APIRouter()


# ── Simulation request/response models ───────────────────────────────────────

class WorkflowSimulateRequest(BaseModel):
    message: str
    context: Optional[Dict[str, Any]] = None
    visual_steps: Optional[Dict[str, Any]] = None  # canvas state (nodes/edges)
    test_session_id: Optional[str] = None          # continue a paused test session
    option_key: Optional[str] = None               # which option the user clicked
    attachments: Optional[List[Dict[str, Any]]] = None  # [{file_name, file_type, file_data?, location?}]

class WorkflowSimulateStep(BaseModel):
    node_id: str
    node_type: str
    label: str
    status: str  # success | error | warning | skipped
    output: str
    duration_ms: int

class WorkflowSimulateResponse(BaseModel):
    steps: List[WorkflowSimulateStep]
    total_duration_ms: int
    test_session_id: str
    # What the workflow produced this turn
    status: str                              # completed | paused_for_input | paused_for_prompt | paused_for_form | error
    response: Optional[str] = None          # bot text to display
    options: Optional[List[Dict[str, Any]]] = None   # [{key, value}] for prompt nodes
    allow_text_input: bool = True
    form_title: Optional[str] = None
    form_fields: Optional[List[Dict[str, Any]]] = None


# ── AI Chat request/response models ───────────────────────────────────────────

class WorkflowAIChatMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str

class WorkflowAIChatRequest(BaseModel):
    message: str
    current_visual_steps: Optional[Dict[str, Any]] = None
    history: List[WorkflowAIChatMessage] = []

class WorkflowAIChatResponse(BaseModel):
    reply: str
    visual_steps: Optional[Dict[str, Any]] = None
    changed_node_ids: List[str] = []

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

@router.post("/{workflow_id}/regenerate-description", dependencies=[Depends(require_permission("workflow:update"))])
def regenerate_workflow_description(
    workflow_id: int,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Regenerate workflow description from visual_steps.
    Useful when the workflow has been updated and you want to refresh the auto-generated description.
    """
    workflow = workflow_service.get_workflow(db, workflow_id, current_user.company_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    visual_steps = workflow.visual_steps
    if isinstance(visual_steps, str):
        try:
            visual_steps = json.loads(visual_steps)
        except json.JSONDecodeError:
            visual_steps = None

    if not visual_steps:
        raise HTTPException(status_code=400, detail="Workflow has no visual_steps to generate description from")

    new_description = workflow_service.generate_workflow_description(visual_steps)
    if not new_description:
        raise HTTPException(status_code=400, detail="Could not generate description from workflow steps")

    workflow.description = new_description
    db.commit()
    db.refresh(workflow)

    return {"description": new_description, "workflow_id": workflow_id}

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

@router.post("/{workflow_id}/ai-chat", response_model=WorkflowAIChatResponse, dependencies=[Depends(require_permission("workflow:update"))])
async def workflow_ai_chat_endpoint(
    workflow_id: int,
    body: WorkflowAIChatRequest,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user),
):
    """
    Natural language workflow editor.
    Send a message describing what you want to change and AI will update the workflow JSON.
    """
    # Verify workflow belongs to company
    wf = workflow_service.get_workflow(db=db, workflow_id=workflow_id, company_id=current_user.company_id)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")

    try:
        result = await workflow_ai_chat(
            db=db,
            company_id=current_user.company_id,
            message=body.message,
            current_visual_steps=body.current_visual_steps,
            history=[{"role": m.role, "content": m.content} for m in body.history],
            workflow=wf,
        )
        return WorkflowAIChatResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI service error: {str(e)}")


@router.post("/{workflow_id}/simulate", response_model=WorkflowSimulateResponse, dependencies=[Depends(require_permission("workflow:read"))])
async def simulate_workflow_endpoint(
    workflow_id: int,
    body: WorkflowSimulateRequest,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user),
):
    """
    Multi-turn workflow test using the real execution engine.
    - First call: omit test_session_id to start a fresh conversation.
    - Subsequent calls: pass the returned test_session_id to continue a paused workflow.
    - For option selections: pass option_key with the chosen key.
    The test session is preserved while paused and cleaned up on completion.
    """
    import time as _time
    import uuid as _uuid
    from app.services.workflow_execution_service import WorkflowExecutionService
    from app.services import conversation_session_service
    from app.schemas.conversation_session import ConversationSessionUpdate
    from app.models.conversation_session import ConversationSession

    wf = workflow_service.get_workflow(db=db, workflow_id=workflow_id, company_id=current_user.company_id)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")

    canvas_visual_steps = body.visual_steps or getattr(wf, "visual_steps", None)
    if not canvas_visual_steps:
        raise HTTPException(status_code=400, detail="No workflow steps to simulate. Save the workflow first or pass visual_steps.")

    # Reuse existing test session (paused workflow) or create a new one
    is_new_session = not body.test_session_id
    test_conversation_id = body.test_session_id or f"__test__{_uuid.uuid4().hex}"

    # Temporarily point the workflow at the canvas visual_steps (not persisted to DB)
    original_visual_steps = wf.visual_steps
    wf.visual_steps = canvas_visual_steps

    execution_trace: List[Dict[str, Any]] = []
    exec_result: Dict[str, Any] = {}
    t0 = _time.monotonic()

    try:
        svc = WorkflowExecutionService(db)

        # On first turn, pre-seed any user-supplied context vars
        if is_new_session and body.context:
            conversation_session_service.get_or_create_session(
                db, test_conversation_id, wf.id,
                contact_id=None, channel="test", company_id=wf.company_id
            )
            conversation_session_service.update_session(
                db, test_conversation_id,
                ConversationSessionUpdate(context=body.context)
            )

        exec_result = await svc.execute_workflow(
            user_message=body.message,
            company_id=current_user.company_id,
            workflow=wf,
            conversation_id=test_conversation_id,
            option_key=body.option_key,
            attachments=body.attachments or [],
            execution_trace=execution_trace,
        ) or {}

    except Exception as exc:
        exec_result = {"status": "error", "response": str(exc)}
        execution_trace.append({
            "node_id": "__error__", "node_type": "error", "label": "Execution Error",
            "status": "error", "output": str(exc), "duration_ms": 0,
        })
    finally:
        wf.visual_steps = original_visual_steps

    total_ms = int((_time.monotonic() - t0) * 1000)

    # Determine what the workflow produced this turn
    raw_status = exec_result.get("status", "completed")

    # Build the bot response text
    bot_response: Optional[str] = None
    raw_resp = exec_result.get("response")
    if isinstance(raw_resp, dict):
        bot_response = raw_resp.get("text") or str(raw_resp)
    elif raw_resp:
        bot_response = str(raw_resp)

    # Options for paused_for_prompt
    options: Optional[List[Dict[str, Any]]] = None
    allow_text_input = True
    if raw_status == "paused_for_prompt":
        prompt_data = exec_result.get("prompt", {}) or {}
        if not bot_response:
            bot_response = prompt_data.get("text", "")
        raw_options = prompt_data.get("options", [])
        options = [
            opt if isinstance(opt, dict) else {"key": str(opt), "value": str(opt)}
            for opt in raw_options
        ]
        allow_text_input = prompt_data.get("allow_text_input", True)

    # Question text for paused_for_input (listen node)
    if raw_status == "paused_for_input" and not bot_response:
        bot_response = exec_result.get("question_text") or "Waiting for your reply…"

    # Form fields for paused_for_form
    form_title: Optional[str] = None
    form_fields: Optional[List[Dict[str, Any]]] = None
    if raw_status == "paused_for_form":
        form_data = exec_result.get("form", {}) or {}
        form_title = form_data.get("title", "Please fill out this form")
        form_fields = form_data.get("fields", [])
        if not bot_response:
            bot_response = form_title

    # Clean up the test session only when the workflow has finished
    is_terminal = raw_status in ("completed", "error", "workflow_transferred")
    if is_terminal:
        try:
            db.query(ConversationSession).filter(
                ConversationSession.conversation_id == test_conversation_id
            ).delete()
            db.commit()
        except Exception:
            logger.exception("Unexpected error")

    return WorkflowSimulateResponse(
        steps=[WorkflowSimulateStep(**s) for s in execution_trace],
        total_duration_ms=total_ms,
        test_session_id=test_conversation_id,
        status=raw_status,
        response=bot_response,
        options=options,
        allow_text_input=allow_text_input,
        form_title=form_title,
        form_fields=form_fields,
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
