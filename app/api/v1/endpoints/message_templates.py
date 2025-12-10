"""
API endpoints for message templates (saved replies).

Provides CRUD operations, search, usage tracking, and variable replacement.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_
from typing import List, Optional
from datetime import datetime

from app.core.dependencies import get_db, get_current_active_user
from app.schemas import message_template as schemas
from app.models import user as models_user
from app.models.message_template import MessageTemplate, TemplateScope
from app.models.conversation_session import ConversationSession
from app.models.company import Company
from app.services.message_template_service import replace_template_variables, get_available_variables

router = APIRouter()


@router.get("/", response_model=schemas.MessageTemplateList)
def list_templates(
    search: Optional[str] = None,
    tags: Optional[str] = None,  # Comma-separated
    scope: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    List all accessible message templates (personal + shared).

    Args:
        search: Search term for name, shortcut, or content
        tags: Comma-separated list of tags to filter by
        scope: Filter by scope ('personal' or 'shared')
        page: Page number (1-indexed)
        page_size: Number of items per page (1-100)

    Returns:
        Paginated list of templates
    """
    # Base query: show personal (created by user) + shared (company-wide)
    query = db.query(MessageTemplate).filter(
        MessageTemplate.company_id == current_user.company_id,
        or_(
            MessageTemplate.scope == TemplateScope.SHARED,
            and_(
                MessageTemplate.scope == TemplateScope.PERSONAL,
                MessageTemplate.created_by_user_id == current_user.id
            )
        )
    )

    # Apply search filter
    if search:
        search_term = f"%{search}%"
        query = query.filter(
            or_(
                MessageTemplate.name.ilike(search_term),
                MessageTemplate.shortcut.ilike(search_term),
                MessageTemplate.content.ilike(search_term)
            )
        )

    # Apply tag filter
    if tags:
        tag_list = [t.strip() for t in tags.split(',') if t.strip()]
        if tag_list:
            query = query.filter(MessageTemplate.tags.overlap(tag_list))

    # Apply scope filter
    if scope and scope in ['personal', 'shared']:
        query = query.filter(MessageTemplate.scope == TemplateScope(scope))

    # Get total count
    total = query.count()

    # Apply pagination and ordering
    skip = (page - 1) * page_size
    templates = query.order_by(
        MessageTemplate.usage_count.desc(),
        MessageTemplate.name
    ).offset(skip).limit(page_size).all()

    return schemas.MessageTemplateList(
        templates=templates,
        total=total,
        page=page,
        page_size=page_size
    )


@router.get("/search", response_model=List[schemas.TemplateSearchResult])
def search_templates(
    query: str = Query(..., min_length=1, description="Search query"),
    limit: int = Query(10, ge=1, le=20, description="Maximum number of results"),
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Fast search for slash command autocomplete.

    Searches by shortcut and name, ordered by usage count.

    Args:
        query: Search query
        limit: Maximum number of results (1-20)

    Returns:
        List of template search results
    """
    search_term = f"%{query}%"

    templates = db.query(MessageTemplate).filter(
        MessageTemplate.company_id == current_user.company_id,
        or_(
            MessageTemplate.scope == TemplateScope.SHARED,
            and_(
                MessageTemplate.scope == TemplateScope.PERSONAL,
                MessageTemplate.created_by_user_id == current_user.id
            )
        ),
        or_(
            MessageTemplate.shortcut.ilike(search_term),
            MessageTemplate.name.ilike(search_term)
        )
    ).order_by(
        MessageTemplate.usage_count.desc(),
        MessageTemplate.shortcut
    ).limit(limit).all()

    # Build search results
    results = []
    for t in templates:
        results.append(schemas.TemplateSearchResult(
            id=t.id,
            shortcut=t.shortcut,
            name=t.name,
            content=t.content,
            preview=t.content[:100] + ('...' if len(t.content) > 100 else ''),
            scope=t.scope.value,
            tags=t.tags or []
        ))

    return results


@router.post("/", response_model=schemas.MessageTemplate)
def create_template(
    template_data: schemas.MessageTemplateCreate,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Create a new message template.

    Validates that the shortcut is unique within accessible templates.

    Args:
        template_data: Template data

    Returns:
        Created template

    Raises:
        400: If shortcut already exists
    """
    # Check for duplicate shortcut (in personal or shared templates)
    existing = db.query(MessageTemplate).filter(
        MessageTemplate.company_id == current_user.company_id,
        MessageTemplate.shortcut == template_data.shortcut.lower(),
        or_(
            MessageTemplate.scope == TemplateScope.SHARED,
            and_(
                MessageTemplate.scope == TemplateScope.PERSONAL,
                MessageTemplate.created_by_user_id == current_user.id
            )
        )
    ).first()

    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Shortcut '{template_data.shortcut}' already exists in your accessible templates"
        )

    # Create template
    template = MessageTemplate(
        company_id=current_user.company_id,
        created_by_user_id=current_user.id,
        name=template_data.name,
        shortcut=template_data.shortcut.lower(),
        content=template_data.content,
        tags=template_data.tags or [],
        scope=TemplateScope(template_data.scope)
    )

    db.add(template)
    db.commit()
    db.refresh(template)

    return template


@router.get("/{template_id}", response_model=schemas.MessageTemplate)
def get_template(
    template_id: int,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Get a specific template.

    Args:
        template_id: Template ID

    Returns:
        Template data

    Raises:
        404: If template not found or not accessible
    """
    template = db.query(MessageTemplate).filter(
        MessageTemplate.id == template_id,
        MessageTemplate.company_id == current_user.company_id,
        or_(
            MessageTemplate.scope == TemplateScope.SHARED,
            and_(
                MessageTemplate.scope == TemplateScope.PERSONAL,
                MessageTemplate.created_by_user_id == current_user.id
            )
        )
    ).first()

    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    return template


@router.put("/{template_id}", response_model=schemas.MessageTemplate)
def update_template(
    template_id: int,
    template_data: schemas.MessageTemplateUpdate,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Update a template (only owner can update).

    Args:
        template_id: Template ID
        template_data: Updated template data

    Returns:
        Updated template

    Raises:
        404: If template not found or user is not the owner
        400: If shortcut already exists (when changing shortcut)
    """
    # Must be owner to update
    template = db.query(MessageTemplate).filter(
        MessageTemplate.id == template_id,
        MessageTemplate.company_id == current_user.company_id,
        MessageTemplate.created_by_user_id == current_user.id
    ).first()

    if not template:
        raise HTTPException(
            status_code=404,
            detail="Template not found or you don't have permission to update it"
        )

    # Get update data
    update_data = template_data.model_dump(exclude_unset=True)

    # Check shortcut uniqueness if being updated
    if 'shortcut' in update_data and update_data['shortcut']:
        existing = db.query(MessageTemplate).filter(
            MessageTemplate.company_id == current_user.company_id,
            MessageTemplate.shortcut == update_data['shortcut'].lower(),
            MessageTemplate.id != template_id,
            or_(
                MessageTemplate.scope == TemplateScope.SHARED,
                and_(
                    MessageTemplate.scope == TemplateScope.PERSONAL,
                    MessageTemplate.created_by_user_id == current_user.id
                )
            )
        ).first()

        if existing:
            raise HTTPException(
                status_code=400,
                detail=f"Shortcut '{update_data['shortcut']}' already exists"
            )

        update_data['shortcut'] = update_data['shortcut'].lower()

    # Convert scope string to enum if present
    if 'scope' in update_data and update_data['scope']:
        update_data['scope'] = TemplateScope(update_data['scope'])

    # Apply updates
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
    Delete a template (only owner can delete).

    Args:
        template_id: Template ID

    Returns:
        Success message

    Raises:
        404: If template not found or user is not the owner
    """
    # Must be owner to delete
    template = db.query(MessageTemplate).filter(
        MessageTemplate.id == template_id,
        MessageTemplate.company_id == current_user.company_id,
        MessageTemplate.created_by_user_id == current_user.id
    ).first()

    if not template:
        raise HTTPException(
            status_code=404,
            detail="Template not found or you don't have permission to delete it"
        )

    db.delete(template)
    db.commit()

    return {"message": "Template deleted successfully"}


@router.post("/{template_id}/use")
def track_template_usage(
    template_id: int,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Track template usage (increment counter and update last used timestamp).

    Args:
        template_id: Template ID

    Returns:
        Success message
    """
    template = db.query(MessageTemplate).filter(
        MessageTemplate.id == template_id,
        MessageTemplate.company_id == current_user.company_id
    ).first()

    if template:
        template.usage_count += 1
        template.last_used_at = datetime.utcnow()
        db.commit()

    return {"message": "Usage tracked"}


@router.get("/variables/available")
def get_available_template_variables(
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Get list of available variables for templates.

    Returns:
        Dictionary with contact_variables, agent_variables, and system_variables
    """
    return get_available_variables()


@router.post("/replace-variables")
def replace_variables_endpoint(
    request: schemas.ReplaceVariablesRequest,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Replace template variables with actual values.

    Used when sending a message to replace variables like {{contact_name}} with actual data.

    Args:
        request: Request with content and optional context (session_id, agent_id)

    Returns:
        Content with variables replaced
    """
    # Get contact from session if provided
    contact = None
    if request.session_id:
        session = db.query(ConversationSession).filter(
            ConversationSession.conversation_id == str(request.session_id)
        ).first()
        if session:
            contact = session.contact

    # Get agent (use current user or specified agent)
    agent = current_user
    if request.agent_id and request.agent_id != current_user.id:
        agent = db.query(models_user.User).filter(
            models_user.User.id == request.agent_id,
            models_user.User.company_id == current_user.company_id
        ).first()
        if not agent:
            agent = current_user  # Fallback to current user

    # Get company
    company = db.query(Company).filter(
        Company.id == current_user.company_id
    ).first()

    # Replace variables
    replaced_content = replace_template_variables(
        content=request.content,
        contact=contact,
        agent=agent,
        company=company
    )

    return {"content": replaced_content}
