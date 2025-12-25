from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional

from app.core.dependencies import get_db, get_current_active_user, require_permission
from app.schemas import tag as schemas_tag
from app.models import user as models_user
from app.models.tag import Tag, lead_tags, contact_tags
from app.models.lead import Lead
from app.models.contact import Contact

router = APIRouter()


@router.get("/", response_model=schemas_tag.TagList, dependencies=[Depends(require_permission("tag:read"))])
def list_tags(
    entity_type: Optional[str] = None,
    search: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    List all tags for the company with usage counts
    """
    query = db.query(Tag).filter(Tag.company_id == current_user.company_id)

    if entity_type and entity_type in ['lead', 'contact', 'both']:
        query = query.filter((Tag.entity_type == entity_type) | (Tag.entity_type == 'both'))

    if search:
        query = query.filter(Tag.name.ilike(f"%{search}%"))

    total = query.count()
    tags = query.order_by(Tag.name).offset(skip).limit(limit).all()

    # Get counts for each tag
    tags_with_counts = []
    for tag in tags:
        lead_count = db.query(func.count(lead_tags.c.lead_id)).filter(
            lead_tags.c.tag_id == tag.id
        ).scalar() or 0

        contact_count = db.query(func.count(contact_tags.c.contact_id)).filter(
            contact_tags.c.tag_id == tag.id
        ).scalar() or 0

        tag_dict = {
            "id": tag.id,
            "name": tag.name,
            "color": tag.color,
            "description": tag.description,
            "entity_type": tag.entity_type,
            "company_id": tag.company_id,
            "created_at": tag.created_at,
            "updated_at": tag.updated_at,
            "lead_count": lead_count,
            "contact_count": contact_count
        }
        tags_with_counts.append(schemas_tag.TagWithCounts(**tag_dict))

    return schemas_tag.TagList(tags=tags_with_counts, total=total)


@router.post("/", response_model=schemas_tag.Tag, dependencies=[Depends(require_permission("tag:create"))])
def create_tag(
    tag_data: schemas_tag.TagCreate,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Create a new tag
    """
    # Check if tag name already exists for this company
    existing = db.query(Tag).filter(
        Tag.company_id == current_user.company_id,
        Tag.name == tag_data.name
    ).first()

    if existing:
        raise HTTPException(status_code=400, detail="Tag with this name already exists")

    tag = Tag(
        name=tag_data.name,
        color=tag_data.color,
        description=tag_data.description,
        entity_type=tag_data.entity_type,
        company_id=current_user.company_id
    )
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return tag


@router.get("/{tag_id}", response_model=schemas_tag.TagWithCounts, dependencies=[Depends(require_permission("tag:read"))])
def get_tag(
    tag_id: int,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Get a specific tag by ID
    """
    tag = db.query(Tag).filter(
        Tag.id == tag_id,
        Tag.company_id == current_user.company_id
    ).first()

    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")

    lead_count = db.query(func.count(lead_tags.c.lead_id)).filter(
        lead_tags.c.tag_id == tag.id
    ).scalar() or 0

    contact_count = db.query(func.count(contact_tags.c.contact_id)).filter(
        contact_tags.c.tag_id == tag.id
    ).scalar() or 0

    return schemas_tag.TagWithCounts(
        id=tag.id,
        name=tag.name,
        color=tag.color,
        description=tag.description,
        entity_type=tag.entity_type,
        company_id=tag.company_id,
        created_at=tag.created_at,
        updated_at=tag.updated_at,
        lead_count=lead_count,
        contact_count=contact_count
    )


@router.put("/{tag_id}", response_model=schemas_tag.Tag, dependencies=[Depends(require_permission("tag:update"))])
def update_tag(
    tag_id: int,
    tag_data: schemas_tag.TagUpdate,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Update a tag
    """
    tag = db.query(Tag).filter(
        Tag.id == tag_id,
        Tag.company_id == current_user.company_id
    ).first()

    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")

    # Check for name collision if name is being updated
    if tag_data.name and tag_data.name != tag.name:
        existing = db.query(Tag).filter(
            Tag.company_id == current_user.company_id,
            Tag.name == tag_data.name,
            Tag.id != tag_id
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail="Tag with this name already exists")

    update_data = tag_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(tag, field, value)

    db.commit()
    db.refresh(tag)
    return tag


@router.delete("/{tag_id}", dependencies=[Depends(require_permission("tag:delete"))])
def delete_tag(
    tag_id: int,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Delete a tag
    """
    tag = db.query(Tag).filter(
        Tag.id == tag_id,
        Tag.company_id == current_user.company_id
    ).first()

    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")

    db.delete(tag)
    db.commit()
    return {"message": "Tag deleted successfully"}


@router.post("/{tag_id}/assign", dependencies=[Depends(require_permission("tag:update"))])
def assign_tag(
    tag_id: int,
    assign_data: schemas_tag.TagAssign,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Assign a tag to multiple leads and/or contacts
    """
    tag = db.query(Tag).filter(
        Tag.id == tag_id,
        Tag.company_id == current_user.company_id
    ).first()

    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")

    assigned_leads = 0
    assigned_contacts = 0

    # Assign to leads
    if assign_data.lead_ids and tag.entity_type in ['lead', 'both']:
        for lead_id in assign_data.lead_ids:
            lead = db.query(Lead).filter(
                Lead.id == lead_id,
                Lead.company_id == current_user.company_id
            ).first()
            if lead and tag not in lead.tag_objects:
                lead.tag_objects.append(tag)
                assigned_leads += 1

    # Assign to contacts
    if assign_data.contact_ids and tag.entity_type in ['contact', 'both']:
        for contact_id in assign_data.contact_ids:
            contact = db.query(Contact).filter(
                Contact.id == contact_id,
                Contact.company_id == current_user.company_id
            ).first()
            if contact and tag not in contact.tag_objects:
                contact.tag_objects.append(tag)
                assigned_contacts += 1

    db.commit()
    return {
        "message": "Tag assigned successfully",
        "assigned_leads": assigned_leads,
        "assigned_contacts": assigned_contacts
    }


@router.post("/{tag_id}/unassign", dependencies=[Depends(require_permission("tag:update"))])
def unassign_tag(
    tag_id: int,
    assign_data: schemas_tag.TagAssign,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Remove a tag from multiple leads and/or contacts
    """
    tag = db.query(Tag).filter(
        Tag.id == tag_id,
        Tag.company_id == current_user.company_id
    ).first()

    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")

    removed_leads = 0
    removed_contacts = 0

    # Remove from leads
    if assign_data.lead_ids:
        for lead_id in assign_data.lead_ids:
            lead = db.query(Lead).filter(
                Lead.id == lead_id,
                Lead.company_id == current_user.company_id
            ).first()
            if lead and tag in lead.tag_objects:
                lead.tag_objects.remove(tag)
                removed_leads += 1

    # Remove from contacts
    if assign_data.contact_ids:
        for contact_id in assign_data.contact_ids:
            contact = db.query(Contact).filter(
                Contact.id == contact_id,
                Contact.company_id == current_user.company_id
            ).first()
            if contact and tag in contact.tag_objects:
                contact.tag_objects.remove(tag)
                removed_contacts += 1

    db.commit()
    return {
        "message": "Tag removed successfully",
        "removed_leads": removed_leads,
        "removed_contacts": removed_contacts
    }
