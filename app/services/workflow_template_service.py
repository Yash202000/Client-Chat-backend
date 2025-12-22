"""
Workflow Template Service
Handles CRUD operations for workflow templates
"""
import json
from typing import List, Optional
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_

from app.models.workflow_template import WorkflowTemplate
from app.models.workflow import Workflow
from app.models.user import User
from app.schemas.workflow_template import (
    WorkflowTemplateCreate,
    WorkflowTemplateFromWorkflow,
    WorkflowTemplateUpdate
)


def get_templates(
    db: Session,
    company_id: int,
    category: Optional[str] = None,
    include_system: bool = True
) -> List[WorkflowTemplate]:
    """
    Get all templates available to a company.
    Returns system templates + company-specific templates.
    """
    query = db.query(WorkflowTemplate).options(
        joinedload(WorkflowTemplate.created_by)
    ).filter(
        WorkflowTemplate.is_active == True
    )

    # Filter: system templates OR company templates
    if include_system:
        query = query.filter(
            or_(
                WorkflowTemplate.is_system == True,
                WorkflowTemplate.company_id == company_id
            )
        )
    else:
        query = query.filter(WorkflowTemplate.company_id == company_id)

    # Filter by category if specified
    if category:
        query = query.filter(WorkflowTemplate.category == category)

    return query.order_by(
        WorkflowTemplate.is_system.desc(),  # System templates first
        WorkflowTemplate.usage_count.desc(),  # Then by popularity
        WorkflowTemplate.name
    ).all()


def get_template(
    db: Session,
    template_id: int,
    company_id: int
) -> Optional[WorkflowTemplate]:
    """
    Get a single template if accessible by the company.
    """
    return db.query(WorkflowTemplate).options(
        joinedload(WorkflowTemplate.created_by)
    ).filter(
        WorkflowTemplate.id == template_id,
        WorkflowTemplate.is_active == True,
        or_(
            WorkflowTemplate.is_system == True,
            WorkflowTemplate.company_id == company_id
        )
    ).first()


def create_template(
    db: Session,
    template_data: WorkflowTemplateCreate,
    company_id: int,
    user_id: int
) -> WorkflowTemplate:
    """
    Create a new template directly (company-specific).
    """
    # Serialize visual_steps if it's a dict
    visual_steps = template_data.visual_steps
    if isinstance(visual_steps, dict):
        visual_steps = json.dumps(visual_steps)

    trigger_phrases = template_data.trigger_phrases or []
    intent_config = template_data.intent_config

    template = WorkflowTemplate(
        name=template_data.name,
        description=template_data.description,
        category=template_data.category,
        icon=template_data.icon,
        visual_steps=visual_steps,
        trigger_phrases=trigger_phrases,
        intent_config=intent_config,
        company_id=company_id,
        created_by_id=user_id,
        is_system=False
    )

    db.add(template)
    db.commit()
    db.refresh(template)
    return template


def create_template_from_workflow(
    db: Session,
    data: WorkflowTemplateFromWorkflow,
    company_id: int,
    user_id: int
) -> Optional[WorkflowTemplate]:
    """
    Save an existing workflow as a template.
    """
    # Get the workflow
    workflow = db.query(Workflow).filter(
        Workflow.id == data.workflow_id,
        Workflow.company_id == company_id
    ).first()

    if not workflow:
        return None

    # Parse visual_steps if it's a string
    visual_steps = workflow.visual_steps
    if isinstance(visual_steps, str):
        visual_steps = json.loads(visual_steps)

    # Parse trigger_phrases if it's a string
    trigger_phrases = workflow.trigger_phrases
    if isinstance(trigger_phrases, str):
        trigger_phrases = json.loads(trigger_phrases)
    trigger_phrases = trigger_phrases or []

    template = WorkflowTemplate(
        name=data.name,
        description=data.description or workflow.description,
        category=data.category,
        icon=data.icon,
        visual_steps=visual_steps,
        trigger_phrases=trigger_phrases,
        intent_config=workflow.intent_config,
        company_id=company_id,
        created_by_id=user_id,
        is_system=False
    )

    db.add(template)
    db.commit()
    db.refresh(template)
    return template


def create_workflow_from_template(
    db: Session,
    template_id: int,
    workflow_name: str,
    workflow_description: Optional[str],
    company_id: int
) -> Optional[Workflow]:
    """
    Create a new workflow from a template.
    No agent is assigned - user will assign later.
    """
    # Get the template
    template = get_template(db, template_id, company_id)
    if not template:
        return None

    # Parse visual_steps if it's a string
    visual_steps = template.visual_steps
    if isinstance(visual_steps, str):
        visual_steps = json.loads(visual_steps)

    # Parse trigger_phrases if it's a string
    trigger_phrases = template.trigger_phrases
    if isinstance(trigger_phrases, str):
        trigger_phrases = json.loads(trigger_phrases)
    trigger_phrases = trigger_phrases or []

    # Create the workflow with no agent
    workflow = Workflow(
        name=workflow_name,
        description=workflow_description or template.description,
        agent_id=None,  # No agent initially
        steps={},  # Empty steps (legacy field)
        visual_steps=json.dumps(visual_steps) if isinstance(visual_steps, dict) else visual_steps,
        trigger_phrases=trigger_phrases,
        intent_config=template.intent_config,
        company_id=company_id,
        version=1,
        is_active=True
    )

    db.add(workflow)
    db.commit()
    db.refresh(workflow)

    # Increment template usage count
    increment_usage_count(db, template_id)

    return workflow


def update_template(
    db: Session,
    template_id: int,
    update_data: WorkflowTemplateUpdate,
    company_id: int
) -> Optional[WorkflowTemplate]:
    """
    Update a company-specific template.
    System templates cannot be updated by companies.
    """
    template = db.query(WorkflowTemplate).filter(
        WorkflowTemplate.id == template_id,
        WorkflowTemplate.company_id == company_id,  # Only company templates
        WorkflowTemplate.is_system == False
    ).first()

    if not template:
        return None

    update_dict = update_data.model_dump(exclude_unset=True)

    # Serialize visual_steps if present
    if 'visual_steps' in update_dict and isinstance(update_dict['visual_steps'], dict):
        update_dict['visual_steps'] = json.dumps(update_dict['visual_steps'])

    for key, value in update_dict.items():
        setattr(template, key, value)

    db.commit()
    db.refresh(template)
    return template


def delete_template(
    db: Session,
    template_id: int,
    company_id: int
) -> bool:
    """
    Delete a company-specific template.
    System templates cannot be deleted by companies.
    """
    template = db.query(WorkflowTemplate).filter(
        WorkflowTemplate.id == template_id,
        WorkflowTemplate.company_id == company_id,  # Only company templates
        WorkflowTemplate.is_system == False
    ).first()

    if not template:
        return False

    db.delete(template)
    db.commit()
    return True


def get_template_categories(db: Session, company_id: int) -> List[str]:
    """
    Get distinct categories from all accessible templates.
    """
    result = db.query(WorkflowTemplate.category).filter(
        WorkflowTemplate.is_active == True,
        WorkflowTemplate.category.isnot(None),
        or_(
            WorkflowTemplate.is_system == True,
            WorkflowTemplate.company_id == company_id
        )
    ).distinct().all()

    return [r[0] for r in result if r[0]]


def increment_usage_count(db: Session, template_id: int) -> None:
    """
    Increment the usage count of a template.
    """
    template = db.query(WorkflowTemplate).filter(
        WorkflowTemplate.id == template_id
    ).first()

    if template:
        template.usage_count = (template.usage_count or 0) + 1
        db.commit()


def seed_system_templates(db: Session) -> int:
    """
    Seed system templates if they don't exist.
    Returns the number of templates created.
    """
    from app.data.workflow_templates import SYSTEM_TEMPLATES

    created_count = 0

    for template_data in SYSTEM_TEMPLATES:
        # Check if template already exists
        existing = db.query(WorkflowTemplate).filter(
            WorkflowTemplate.name == template_data['name'],
            WorkflowTemplate.is_system == True
        ).first()

        if not existing:
            template = WorkflowTemplate(
                name=template_data['name'],
                description=template_data['description'],
                category=template_data['category'],
                icon=template_data.get('icon'),
                visual_steps=template_data['visual_steps'],
                trigger_phrases=template_data.get('trigger_phrases', []),
                intent_config=template_data.get('intent_config'),
                company_id=None,
                created_by_id=None,
                is_system=True,
                is_active=True
            )
            db.add(template)
            created_count += 1

    if created_count > 0:
        db.commit()

    return created_count
