"""
Voice Workflow API Endpoints.

This module provides the FastAPI endpoints for the Hybrid Voice-Web Workflow system:
- Start voice workflow session (creates LiveKit room)
- Handle workflow steps from the agent
- Render dynamic forms
- Process form submissions
- Handle human agent handoff
"""
import os
import json
import logging
from typing import Optional
from datetime import datetime
from fastapi import APIRouter, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from app.schemas.voice_workflow import (
    StartVoiceWorkflowRequest,
    StartVoiceWorkflowResponse,
    WorkflowStepRequest,
    WorkflowStepResponse,
    HandoffRequest,
    HandoffResponse,
    FormField
)
from app.services import workflow_livekit_service, voice_workflow_session_service

logger = logging.getLogger(__name__)

router = APIRouter()

# Setup Jinja2 templates
templates_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "templates")
templates = Jinja2Templates(directory=templates_dir)


@router.post("/start-session", response_model=StartVoiceWorkflowResponse)
async def start_voice_workflow_session(request: StartVoiceWorkflowRequest):
    """
    Start a new voice workflow session.
    
    Creates a LiveKit room with the workflow JSON attached to room metadata.
    If workflow_json is not provided, fetches the active workflow for the agent from DB.
    Returns tokens for both user and agent to join the room.
    """
    try:
        # DEBUG: Log what we received from frontend
        logger.info(f"[VOICE WORKFLOW] === START SESSION REQUEST ===")
        logger.info(f"[VOICE WORKFLOW] agent_id: {request.agent_id}")
        logger.info(f"[VOICE WORKFLOW] company_id: {request.company_id}")
        logger.info(f"[VOICE WORKFLOW] workflow_json provided by frontend: {request.workflow_json is not None}")
        
        workflow_json = None  # Always start fresh, ignore frontend workflow_json
        
        # ALWAYS fetch from database when agent_id is provided (ignore frontend workflow)
        if request.agent_id:
            from app.core.database import SessionLocal
            from app.services import workflow_service
            
            db = SessionLocal()
            try:
                # Get active workflows for this agent
                from app.models import workflow as models_workflow, agent as models_agent
                from app.models.workflow import agent_workflows
                
                # Helper to parse visual_steps (may be string or dict)
                def parse_visual_steps(vs):
                    if vs is None:
                        return {}
                    if isinstance(vs, str):
                        try:
                            return json.loads(vs)
                        except:
                            return {}
                    return vs
                
                # First log ALL active workflows to debug
                all_workflows = db.query(models_workflow.Workflow).filter(
                    models_workflow.Workflow.is_active == True
                ).all()
                
                logger.info(f"[VOICE WORKFLOW] Found {len(all_workflows)} active workflows in DB:")
                for w in all_workflows:
                    vs = parse_visual_steps(w.visual_steps)
                    vs_nodes = len(vs.get('nodes', [])) if vs else 0
                    logger.info(f"  - id={w.id}, name={w.name}, visual_steps_nodes={vs_nodes}")
                
                # Find workflow with visual_steps that has nodes (the real workflow, not default)
                workflow = None
                for w in all_workflows:
                    vs = parse_visual_steps(w.visual_steps)
                    if vs and len(vs.get('nodes', [])) > 0:
                        workflow = w
                        logger.info(f"[VOICE WORKFLOW] Selected workflow with nodes: {w.name}")
                        break
                
                # If no workflow with nodes found, use first one
                if not workflow and all_workflows:
                    workflow = all_workflows[0]
                    logger.warning(f"[VOICE WORKFLOW] No workflow with nodes found, using: {workflow.name}")
                
                if workflow:
                    # Build workflow_json from visual_steps (parse if string)
                    visual_steps = parse_visual_steps(workflow.visual_steps)
                    workflow_json = {
                        "id": workflow.id,
                        "name": workflow.name,
                        "description": workflow.description or "",
                        "visual_steps": visual_steps,
                        # Also include nodes/edges at root for compatibility
                        "nodes": visual_steps.get("nodes", []),
                        "edges": visual_steps.get("edges", [])
                    }
                    logger.info(f"[VOICE WORKFLOW] Final workflow: {workflow.name} with {len(visual_steps.get('nodes', []))} nodes")
                else:
                    logger.warning(f"[VOICE WORKFLOW] No active workflow found for agent {request.agent_id}")
                    raise ValueError(f"No active workflow found for agent {request.agent_id}")
            finally:
                db.close()
        
        if not workflow_json:
            raise ValueError("Either workflow_json or agent_id must be provided")
        
        result = workflow_livekit_service.create_workflow_room(
            workflow_json=workflow_json,
            user_name=request.user_name or "Customer",
            greeting_message=request.greeting_message,
            agent_id=request.agent_id,
            company_id=request.company_id
        )
        
        # Actually create the room on LiveKit server to trigger agent dispatch
        await workflow_livekit_service.create_room_on_server(
            room_name=result["room_name"],
            metadata_json=result["metadata_json"]
        )
        
        # Create session in memory for form handling
        voice_workflow_session_service.create_session(
            session_id=result["session_id"],
            room_name=result["room_name"],
            workflow_json=workflow_json
        )
        
        return StartVoiceWorkflowResponse(
            success=True,
            session_id=result["session_id"],
            room_name=result["room_name"],
            livekit_url=result["livekit_url"],
            user_token=result["user_token"],
            agent_token=result["agent_token"],
            status="starting",
            message="Voice workflow session initiated. Connect to the room to begin."
        )
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to start voice workflow session: {e}")
        raise HTTPException(status_code=500, detail="Failed to start voice session")


@router.get("/session/{session_id}")
async def get_session_data(session_id: str):
    """
    Get session data including workflow JSON.
    Used by the agent as a fallback when room metadata is empty.
    """
    session = voice_workflow_session_service.get_session(session_id)
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired")
    
    return {
        "session_id": session_id,
        "room_name": session.get("room_name"),
        "workflow_json": session.get("workflow_json"),
        "voice_data": session.get("voice_data", {}),
        "status": session.get("status", "active")
    }


@router.post("/step", response_model=WorkflowStepResponse)
async def handle_workflow_step(request: WorkflowStepRequest):
    """
    Handle a workflow step action from the agent.
    
    Actions:
    - 'create_incident': Create an incident record
    - 'request_files': Request file upload from user (returns form URL)
    - 'request_handoff': Request human agent handoff
    - 'update_data': Update session with voice-captured data
    """
    session = voice_workflow_session_service.get_session(request.session_id)
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired")
    
    # Parse the data JSON
    try:
        data = json.loads(request.data) if request.data else {}
    except json.JSONDecodeError:
        data = {}
    
    action = request.action.lower()
    
    # ==== NEW: store_data - Save structured voice data ====
    if action == "store_data":
        # Store voice-captured data with variable name mapping
        logger.info(f"Storing data for session {request.session_id}: {data}")
        voice_workflow_session_service.update_session(
            session_id=request.session_id,
            voice_data=data
        )
        return WorkflowStepResponse(
            status="success",
            message="Data stored successfully",
            data=data
        )
    
    # ==== NEW: request_form - Request form for attachment/location ====
    elif action == "request_form":
        field_type = data.get("field_type", "attachment")
        variable_name = data.get("variable_name", "file_upload")
        
        logger.info(f"Requesting form for {field_type} -> {variable_name}")
        
        # Create form fields based on type
        if field_type == "attachment":
            required_fields = [
                FormField(
                    name=variable_name,
                    field_type="file",
                    label="Upload File or Image",
                    required=True
                )
            ]
        elif field_type == "location":
            required_fields = [
                FormField(
                    name=variable_name,
                    field_type="location",
                    label="Share Your Location",
                    required=True
                )
            ]
        else:
            required_fields = [
                FormField(
                    name=variable_name,
                    field_type="file",
                    label=f"Upload {field_type}",
                    required=True
                )
            ]
        
        # Update session with required fields and pending form status
        session.required_fields = required_fields
        voice_workflow_session_service.update_session(
            session_id=request.session_id,
            status="waiting_for_form"
        )
        
        # Generate form URL
        form_url = workflow_livekit_service.generate_form_url(request.session_id)
        
        return WorkflowStepResponse(
            status="waiting_for_input",
            message=f"Form sent for {field_type}",
            url=form_url
        )
    
    # ==== NEW: execute_step - Execute workflow code/HTTP nodes ====
    elif action == "execute_step":
        step_id = data.get("step_id", "")
        step_type = data.get("step_type", "code")
        
        logger.info(f"Executing step {step_id} (type: {step_type})")
        
        try:
            # Import workflow execution service
            from app.services.workflow_execution_service import WorkflowExecutionService
            from app.core.database import SessionLocal
            
            db = SessionLocal()
            try:
                workflow_exec = WorkflowExecutionService(db)
                
                # Get node data from workflow
                nodes = session.workflow_json.get("visual_steps", {}).get("nodes", [])
                node_data = None
                for node in nodes:
                    if node.get("id") == step_id:
                        node_data = node.get("data", {})
                        break
                
                if not node_data:
                    return WorkflowStepResponse(
                        status="error",
                        message=f"Step {step_id} not found in workflow"
                    )
                
                # Build context from collected data
                context = session.voice_captured_data.copy()
                results = {}
                
                # Execute based on step type
                if step_type == "code":
                    result = await workflow_exec._execute_code_node(node_data, context, results)
                elif step_type == "http_request":
                    result = await workflow_exec._execute_http_request_node(node_data, context, results)
                else:
                    result = {"output": "Step type not supported"}
                
                # Store result in session
                voice_workflow_session_service.update_session(
                    session_id=request.session_id,
                    voice_data={step_id: result}
                )
                
                return WorkflowStepResponse(
                    status="success",
                    message="Step executed successfully",
                    data=result
                )
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Step execution failed: {e}")
            return WorkflowStepResponse(
                status="error",
                message=f"Step execution failed: {str(e)}"
            )
    
    # ==== Legacy: update_data ====
    elif action == "update_data":
        # Store voice-captured data
        voice_workflow_session_service.update_session(
            session_id=request.session_id,
            voice_data=data
        )
        return WorkflowStepResponse(
            status="success",
            message="Data updated successfully"
        )
    
    # ==== Legacy: request_files ====
    elif action == "request_files" or action == "request_input":
        # Store any voice data first
        if data:
            voice_workflow_session_service.update_session(
                session_id=request.session_id,
                voice_data=data
            )
        
        # Determine required fields based on workflow
        required_fields = voice_workflow_session_service.determine_required_fields(
            session.workflow_json,
            session.voice_captured_data
        )
        
        # If no specific fields determined, add default file upload
        if not required_fields:
            required_fields = [
                FormField(
                    name="file_upload",
                    field_type="file",
                    label="Upload File or Image",
                    required=True
                ),
                FormField(
                    name="additional_notes",
                    field_type="textarea",
                    label="Additional Notes (optional)",
                    required=False
                )
            ]
        
        # Update session with required fields
        session.required_fields = required_fields
        voice_workflow_session_service.update_session(
            session_id=request.session_id,
            status="waiting_for_form"
        )
        
        # Generate form URL
        form_url = workflow_livekit_service.generate_form_url(request.session_id)
        
        return WorkflowStepResponse(
            status="waiting_for_input",
            message="Please fill out the form to continue",
            url=form_url
        )
    
    elif action == "create_incident":
        # Get all collected data
        all_data = voice_workflow_session_service.complete_session(request.session_id)
        
        # Here you would integrate with your incident creation service
        # For now, return success with the collected data
        return WorkflowStepResponse(
            status="success",
            message="Incident created successfully",
            data=all_data
        )
    
    elif action == "request_handoff":
        # This will be handled by the /handoff endpoint
        return WorkflowStepResponse(
            status="redirect",
            message="Use the /handoff endpoint for human agent handoff"
        )
    
    else:
        return WorkflowStepResponse(
            status="error",
            message=f"Unknown action: {action}"
        )


@router.get("/form/{session_id}", response_class=HTMLResponse)
async def render_form(request: Request, session_id: str):
    """
    Render the dynamic form for a voice workflow session.
    
    The form fields are determined by what's still needed after voice capture.
    """
    session = voice_workflow_session_service.get_session(session_id)
    
    if not session:
        return HTMLResponse(
            content="<html><body><h1>Session Not Found</h1><p>This form link has expired or is invalid.</p></body></html>",
            status_code=404
        )
    
    # Get or generate required fields
    fields = session.required_fields
    if not fields:
        fields = voice_workflow_session_service.determine_required_fields(
            session.workflow_json,
            session.voice_captured_data
        )
    
    return templates.TemplateResponse(
        "voice_forms/dynamic_form.html",
        {
            "request": request,
            "session_id": session_id,
            "fields": fields,
            "voice_data": session.voice_captured_data,
            "workflow_name": session.workflow_json.get("name", "Workflow")
        }
    )


@router.post("/submit/{session_id}")
async def submit_form(
    session_id: str,
    request: Request
):
    """
    Process form submission for a voice workflow session.
    
    Handles both regular form fields and file uploads.
    Notifies the agent that the form has been submitted.
    """
    session = voice_workflow_session_service.get_session(session_id)
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired")
    
    # Parse form data
    form_data = await request.form()
    processed_data = {}
    
    for key, value in form_data.items():
        if isinstance(value, UploadFile):
            # Handle file upload
            if value.filename:
                # Save file to uploads directory
                upload_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..", "uploads", session_id)
                os.makedirs(upload_dir, exist_ok=True)
                
                file_path = os.path.join(upload_dir, value.filename)
                content = await value.read()
                
                with open(file_path, "wb") as f:
                    f.write(content)
                
                processed_data[key] = {
                    "filename": value.filename,
                    "path": file_path,
                    "content_type": value.content_type,
                    "size": len(content)
                }
                logger.info(f"Saved uploaded file: {value.filename}")
        else:
            # Regular form field
            if value:  # Only include non-empty values
                processed_data[key] = value
    
    # Update session with form data
    voice_workflow_session_service.update_session(
        session_id=session_id,
        form_data=processed_data,
        status="form_submitted"
    )
    
    # Send data message to LiveKit room to notify agent
    try:
        await workflow_livekit_service.send_data_message_to_room(
            room_name=session.room_name,
            message_type="FORM_SUBMITTED",
            data={
                "session_id": session_id,
                "fields_submitted": list(processed_data.keys()),
                "timestamp": datetime.utcnow().isoformat()
            }
        )
    except Exception as e:
        logger.warning(f"Could not notify agent of form submission: {e}")
    
    return {
        "success": True,
        "message": "Form submitted successfully",
        "session_id": session_id
    }


@router.post("/handoff", response_model=HandoffResponse)
async def request_handoff(request: HandoffRequest):
    """
    Request handoff to a human agent.
    
    This triggers the agent assignment service to find an available agent
    and provides them with the conversation transcript.
    """
    session = voice_workflow_session_service.get_session(request.session_id)
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    try:
        # Import the agent assignment service
        from app.services import agent_assignment_service
        from app.core.database import SessionLocal
        
        db = SessionLocal()
        try:
            # Use the existing handoff logic
            result = await agent_assignment_service.request_handoff(
                db=db,
                session_id=request.session_id,
                reason=request.reason,
                team_name=request.team_name,
                priority=request.priority
            )
            
            return HandoffResponse(
                status=result.get("status", "error"),
                message=result.get("message", "Handoff requested"),
                agent_id=result.get("agent_id"),
                agent_name=result.get("agent_name")
            )
        finally:
            db.close()
            
    except Exception as e:
        logger.error(f"Handoff request failed: {e}")
        return HandoffResponse(
            status="error",
            message=f"Failed to request handoff: {str(e)}"
        )


@router.get("/session/{session_id}")
async def get_session_status(session_id: str):
    """
    Get the current status of a voice workflow session.
    """
    session = voice_workflow_session_service.get_session(session_id)
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    return {
        "session_id": session_id,
        "status": session.status,
        "room_name": session.room_name,
        "created_at": session.created_at.isoformat(),
        "voice_data_collected": list(session.voice_captured_data.keys()),
        "required_fields": [f.name for f in session.required_fields],
        "workflow_name": session.workflow_json.get("name", "Unknown")
    }


@router.delete("/session/{session_id}")
async def delete_session(session_id: str):
    """
    Delete a voice workflow session.
    """
    if voice_workflow_session_service.delete_session(session_id):
        return {"success": True, "message": "Session deleted"}
    raise HTTPException(status_code=404, detail="Session not found")


@router.get("/config")
async def get_voice_workflow_config():
    """
    Get the current voice workflow configuration (for debugging).
    """
    return workflow_livekit_service.get_livekit_config()
