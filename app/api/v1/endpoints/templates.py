from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_
from typing import List, Optional

from app.core.dependencies import get_db, get_current_active_user
from app.schemas import template as schemas_template
from app.models import user as models_user
from app.models.template import Template, TemplateType

router = APIRouter()


@router.get("", response_model=schemas_template.TemplateList)
def list_templates(
    search: Optional[str] = None,
    template_type: Optional[str] = None,
    tags: Optional[str] = None,  # Comma-separated tags
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    List all templates for the company with filtering and pagination
    """
    query = db.query(Template).filter(Template.company_id == current_user.company_id)

    # Search by name or description
    if search:
        search_term = f"%{search}%"
        query = query.filter(
            or_(
                Template.name.ilike(search_term),
                Template.description.ilike(search_term)
            )
        )

    # Filter by type
    if template_type and template_type in ['email', 'sms', 'whatsapp', 'voice']:
        query = query.filter(Template.template_type == TemplateType(template_type))

    # Filter by tags
    if tags:
        tag_list = [t.strip() for t in tags.split(',')]
        query = query.filter(Template.tags.overlap(tag_list))

    # Get total count
    total = query.count()

    # Apply pagination
    skip = (page - 1) * page_size
    templates = query.order_by(Template.updated_at.desc()).offset(skip).limit(page_size).all()

    return schemas_template.TemplateList(
        templates=templates,
        total=total,
        page=page,
        page_size=page_size
    )


@router.post("", response_model=schemas_template.Template)
def create_template(
    template_data: schemas_template.TemplateCreate,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Create a new template
    """
    template = Template(
        company_id=current_user.company_id,
        created_by_user_id=current_user.id,
        name=template_data.name,
        description=template_data.description,
        template_type=TemplateType(template_data.template_type),
        subject=template_data.subject,
        body=template_data.body,
        html_body=template_data.html_body,
        voice_script=template_data.voice_script,
        tts_voice_id=template_data.tts_voice_id,
        whatsapp_template_name=template_data.whatsapp_template_name,
        whatsapp_template_params=template_data.whatsapp_template_params,
        personalization_tokens=template_data.personalization_tokens or [],
        tags=template_data.tags or [],
        is_ai_generated=template_data.is_ai_generated or False
    )

    db.add(template)
    db.commit()
    db.refresh(template)

    return template


@router.get("/{template_id}", response_model=schemas_template.Template)
def get_template(
    template_id: int,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Get a specific template by ID
    """
    template = db.query(Template).filter(
        Template.id == template_id,
        Template.company_id == current_user.company_id
    ).first()

    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    return template


@router.put("/{template_id}", response_model=schemas_template.Template)
def update_template(
    template_id: int,
    template_data: schemas_template.TemplateUpdate,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Update an existing template
    """
    template = db.query(Template).filter(
        Template.id == template_id,
        Template.company_id == current_user.company_id
    ).first()

    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    update_data = template_data.model_dump(exclude_unset=True)

    # Handle template_type conversion
    if 'template_type' in update_data and update_data['template_type']:
        update_data['template_type'] = TemplateType(update_data['template_type'])

    for field, value in update_data.items():
        setattr(template, field, value)

    db.commit()
    db.refresh(template)

    return template


@router.delete("/{template_id}")
def delete_template(
    template_id: int,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Delete a template
    """
    template = db.query(Template).filter(
        Template.id == template_id,
        Template.company_id == current_user.company_id
    ).first()

    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    db.delete(template)
    db.commit()

    return {"message": "Template deleted successfully"}


@router.post("/{template_id}/duplicate", response_model=schemas_template.Template)
def duplicate_template(
    template_id: int,
    duplicate_data: schemas_template.TemplateDuplicate,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Duplicate an existing template with a new name
    """
    original = db.query(Template).filter(
        Template.id == template_id,
        Template.company_id == current_user.company_id
    ).first()

    if not original:
        raise HTTPException(status_code=404, detail="Template not found")

    # Create a copy with the new name
    duplicate = Template(
        company_id=current_user.company_id,
        created_by_user_id=current_user.id,
        name=duplicate_data.new_name,
        description=original.description,
        template_type=original.template_type,
        subject=original.subject,
        body=original.body,
        html_body=original.html_body,
        voice_script=original.voice_script,
        tts_voice_id=original.tts_voice_id,
        whatsapp_template_name=original.whatsapp_template_name,
        whatsapp_template_params=original.whatsapp_template_params,
        personalization_tokens=original.personalization_tokens,
        tags=original.tags,
        is_ai_generated=False  # Duplicates are not AI-generated
    )

    db.add(duplicate)
    db.commit()
    db.refresh(duplicate)

    return duplicate


@router.get("/types/available")
def get_available_types(
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Get list of available template types
    """
    return {
        "types": [
            {"value": "email", "label": "Email", "description": "Email templates with subject and HTML body"},
            {"value": "sms", "label": "SMS", "description": "Short text messages (160-320 chars)"},
            {"value": "whatsapp", "label": "WhatsApp", "description": "WhatsApp message templates"},
            {"value": "voice", "label": "Voice", "description": "Voice call scripts for TTS"}
        ]
    }


@router.get("/tokens/available")
def get_available_tokens(
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Get list of available personalization tokens
    """
    return {
        "tokens": [
            {"token": "{{first_name}}", "description": "Contact's first name"},
            {"token": "{{last_name}}", "description": "Contact's last name"},
            {"token": "{{full_name}}", "description": "Contact's full name"},
            {"token": "{{email}}", "description": "Contact's email address"},
            {"token": "{{phone}}", "description": "Contact's phone number"},
            {"token": "{{company}}", "description": "Contact's company name"},
            {"token": "{{job_title}}", "description": "Contact's job title"},
            {"token": "{{lead_score}}", "description": "Lead's score"},
            {"token": "{{deal_value}}", "description": "Associated deal value"},
            {"token": "{{lifecycle_stage}}", "description": "Contact's lifecycle stage"},
            {"token": "{{unsubscribe_link}}", "description": "Unsubscribe link (email only)"},
            {"token": "{{current_date}}", "description": "Current date"},
            {"token": "{{company_name}}", "description": "Your company name"}
        ]
    }
