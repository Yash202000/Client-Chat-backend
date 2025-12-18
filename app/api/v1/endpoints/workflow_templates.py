"""
Workflow Templates API Endpoints
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional

from app.schemas.workflow_template import (
    WorkflowTemplateCreate,
    WorkflowTemplateFromWorkflow,
    WorkflowFromTemplate,
    WorkflowTemplateUpdate,
    WorkflowTemplateResponse,
    WorkflowTemplateListItem
)
from app.schemas.workflow import Workflow as WorkflowSchema
from app.services import workflow_template_service
from app.core.dependencies import get_db, get_current_active_user, require_permission
from app.models.user import User

router = APIRouter()


def _build_template_response(template, include_full: bool = True) -> dict:
    """Helper to build template response with created_by_name"""
    created_by_name = None
    if template.created_by:
        if template.created_by.first_name and template.created_by.last_name:
            created_by_name = f"{template.created_by.first_name} {template.created_by.last_name}"
        elif template.created_by.first_name:
            created_by_name = template.created_by.first_name
        else:
            created_by_name = template.created_by.email

    # Count nodes
    node_count = 0
    visual_steps = template.visual_steps
    if isinstance(visual_steps, dict) and 'nodes' in visual_steps:
        node_count = len(visual_steps.get('nodes', []))
    elif isinstance(visual_steps, str):
        import json
        try:
            parsed = json.loads(visual_steps)
            node_count = len(parsed.get('nodes', []))
        except:
            pass

    base_data = {
        "id": template.id,
        "name": template.name,
        "description": template.description,
        "category": template.category,
        "icon": template.icon,
        "is_system": template.is_system,
        "usage_count": template.usage_count or 0,
        "created_at": template.created_at,
        "node_count": node_count
    }

    if include_full:
        # Parse visual_steps if string
        visual_steps = template.visual_steps
        if isinstance(visual_steps, str):
            import json
            visual_steps = json.loads(visual_steps)

        trigger_phrases = template.trigger_phrases
        if isinstance(trigger_phrases, str):
            import json
            trigger_phrases = json.loads(trigger_phrases)

        base_data.update({
            "visual_steps": visual_steps,
            "trigger_phrases": trigger_phrases or [],
            "intent_config": template.intent_config,
            "company_id": template.company_id,
            "updated_at": template.updated_at,
            "created_by_name": created_by_name
        })

    return base_data


@router.get("/", response_model=List[WorkflowTemplateListItem],
            dependencies=[Depends(require_permission("workflow:read"))])
def list_templates(
    category: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    List all workflow templates (system + company-specific).
    """
    templates = workflow_template_service.get_templates(
        db=db,
        company_id=current_user.company_id,
        category=category
    )

    return [_build_template_response(t, include_full=False) for t in templates]


@router.get("/categories", dependencies=[Depends(require_permission("workflow:read"))])
def get_categories(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Get distinct template categories.
    """
    categories = workflow_template_service.get_template_categories(db, current_user.company_id)
    return {"categories": categories}


@router.get("/{template_id}", response_model=WorkflowTemplateResponse,
            dependencies=[Depends(require_permission("workflow:read"))])
def get_template(
    template_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Get a single template by ID.
    """
    template = workflow_template_service.get_template(db, template_id, current_user.company_id)

    if not template:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")

    return _build_template_response(template, include_full=True)


@router.post("/", response_model=WorkflowTemplateResponse, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_permission("workflow:create"))])
def create_template(
    template_data: WorkflowTemplateCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Create a new template directly.
    """
    template = workflow_template_service.create_template(
        db=db,
        template_data=template_data,
        company_id=current_user.company_id,
        user_id=current_user.id
    )

    return _build_template_response(template, include_full=True)


@router.post("/from-workflow", response_model=WorkflowTemplateResponse, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_permission("workflow:create"))])
def save_workflow_as_template(
    data: WorkflowTemplateFromWorkflow,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Save an existing workflow as a template.
    """
    template = workflow_template_service.create_template_from_workflow(
        db=db,
        data=data,
        company_id=current_user.company_id,
        user_id=current_user.id
    )

    if not template:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")

    return _build_template_response(template, include_full=True)


@router.post("/{template_id}/create-workflow", status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_permission("workflow:create"))])
def create_workflow_from_template(
    template_id: int,
    data: WorkflowFromTemplate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Create a new workflow from a template.
    The workflow will be created without an agent - assign one later.
    """
    workflow = workflow_template_service.create_workflow_from_template(
        db=db,
        template_id=template_id,
        workflow_name=data.name,
        workflow_description=data.description,
        company_id=current_user.company_id
    )

    if not workflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")

    return {
        "id": workflow.id,
        "name": workflow.name,
        "description": workflow.description,
        "agent_id": workflow.agent_id,
        "message": "Workflow created from template. Please assign an agent in the workflow builder."
    }


@router.put("/{template_id}", response_model=WorkflowTemplateResponse,
            dependencies=[Depends(require_permission("workflow:update"))])
def update_template(
    template_id: int,
    update_data: WorkflowTemplateUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Update a company-specific template.
    System templates cannot be updated.
    """
    template = workflow_template_service.update_template(
        db=db,
        template_id=template_id,
        update_data=update_data,
        company_id=current_user.company_id
    )

    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Template not found or cannot be updated (system templates are read-only)"
        )

    return _build_template_response(template, include_full=True)


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT,
               dependencies=[Depends(require_permission("workflow:delete"))])
def delete_template(
    template_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Delete a company-specific template.
    System templates cannot be deleted.
    """
    success = workflow_template_service.delete_template(
        db=db,
        template_id=template_id,
        company_id=current_user.company_id
    )

    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Template not found or cannot be deleted (system templates are read-only)"
        )

    return None
