from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, or_, and_
from typing import List, Optional

from app.core.dependencies import get_db, get_current_active_user
from app.schemas import segment as schemas_segment
from app.models import user as models_user
from app.models.segment import Segment, SegmentType
from app.models.contact import Contact, LifecycleStage, OptInStatus
from app.models.lead import Lead, LeadStage
from app.models.tag import Tag, lead_tags, contact_tags
from datetime import datetime

router = APIRouter()


def get_segment_members(db: Session, segment: Segment, company_id: int, skip: int = 0, limit: int = 100):
    """Get the leads and contacts matching a segment's criteria"""
    contacts = []
    leads = []

    if segment.segment_type == SegmentType.STATIC:
        # Static segment - use stored IDs
        if segment.static_contact_ids:
            contacts = db.query(Contact).filter(
                Contact.id.in_(segment.static_contact_ids),
                Contact.company_id == company_id
            ).all()
        if segment.static_lead_ids:
            leads = db.query(Lead).filter(
                Lead.id.in_(segment.static_lead_ids),
                Lead.company_id == company_id
            ).all()
    else:
        # Dynamic segment - apply criteria filters
        criteria = segment.criteria or {}

        # Contact query
        if criteria.get('include_contacts', True):
            contact_query = db.query(Contact).filter(
                Contact.company_id == company_id,
                Contact.do_not_contact == False
            )

            if criteria.get('lifecycle_stages'):
                stages = [LifecycleStage(s) for s in criteria['lifecycle_stages'] if s in [e.value for e in LifecycleStage]]
                if stages:
                    contact_query = contact_query.filter(Contact.lifecycle_stage.in_(stages))

            if criteria.get('lead_sources'):
                contact_query = contact_query.filter(Contact.lead_source.in_(criteria['lead_sources']))

            if criteria.get('opt_in_status'):
                statuses = [OptInStatus(s) for s in criteria['opt_in_status'] if s in [e.value for e in OptInStatus]]
                if statuses:
                    contact_query = contact_query.filter(Contact.opt_in_status.in_(statuses))

            if criteria.get('tag_ids'):
                contact_query = contact_query.join(contact_tags).filter(
                    contact_tags.c.tag_id.in_(criteria['tag_ids'])
                )

            contacts = contact_query.all()

        # Lead query
        if criteria.get('include_leads', True):
            lead_query = db.query(Lead).filter(Lead.company_id == company_id)

            if criteria.get('lead_stages'):
                stages = [LeadStage(s) for s in criteria['lead_stages'] if s in [e.value for e in LeadStage]]
                if stages:
                    lead_query = lead_query.filter(Lead.stage.in_(stages))

            if criteria.get('score_min') is not None:
                lead_query = lead_query.filter(Lead.score >= criteria['score_min'])

            if criteria.get('score_max') is not None:
                lead_query = lead_query.filter(Lead.score <= criteria['score_max'])

            if criteria.get('tag_ids'):
                lead_query = lead_query.join(lead_tags).filter(
                    lead_tags.c.tag_id.in_(criteria['tag_ids'])
                )

            leads = lead_query.all()

    return contacts, leads


def count_segment_members(db: Session, segment: Segment, company_id: int):
    """Count leads and contacts matching segment criteria"""
    contacts, leads = get_segment_members(db, segment, company_id)
    return len(contacts), len(leads)


@router.get("/", response_model=schemas_segment.SegmentList)
def list_segments(
    search: Optional[str] = None,
    segment_type: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    List all segments for the company
    """
    query = db.query(Segment).filter(Segment.company_id == current_user.company_id)

    if search:
        query = query.filter(Segment.name.ilike(f"%{search}%"))

    if segment_type and segment_type in ['dynamic', 'static']:
        query = query.filter(Segment.segment_type == SegmentType(segment_type))

    total = query.count()
    segments = query.order_by(Segment.name).offset(skip).limit(limit).all()

    return schemas_segment.SegmentList(segments=segments, total=total)


@router.post("/", response_model=schemas_segment.Segment)
def create_segment(
    segment_data: schemas_segment.SegmentCreate,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Create a new segment
    """
    segment = Segment(
        name=segment_data.name,
        description=segment_data.description,
        segment_type=SegmentType(segment_data.segment_type) if segment_data.segment_type else SegmentType.DYNAMIC,
        criteria=segment_data.criteria.model_dump() if segment_data.criteria else None,
        static_contact_ids=segment_data.static_contact_ids,
        static_lead_ids=segment_data.static_lead_ids,
        company_id=current_user.company_id,
        created_by_user_id=current_user.id
    )

    db.add(segment)
    db.commit()

    # Calculate initial counts
    contact_count, lead_count = count_segment_members(db, segment, current_user.company_id)
    segment.contact_count = contact_count
    segment.lead_count = lead_count
    segment.last_refreshed_at = datetime.utcnow()
    db.commit()
    db.refresh(segment)

    return segment


@router.get("/{segment_id}", response_model=schemas_segment.Segment)
def get_segment(
    segment_id: int,
    refresh_counts: bool = Query(default=True, description="Recalculate member counts"),
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Get a specific segment by ID
    """
    segment = db.query(Segment).filter(
        Segment.id == segment_id,
        Segment.company_id == current_user.company_id
    ).first()

    if not segment:
        raise HTTPException(status_code=404, detail="Segment not found")

    # Optionally refresh counts (default: True for accurate counts)
    if refresh_counts:
        contact_count, lead_count = count_segment_members(db, segment, current_user.company_id)
        segment.contact_count = contact_count
        segment.lead_count = lead_count
        segment.last_refreshed_at = datetime.utcnow()
        db.commit()
        db.refresh(segment)

    return segment


@router.put("/{segment_id}", response_model=schemas_segment.Segment)
def update_segment(
    segment_id: int,
    segment_data: schemas_segment.SegmentUpdate,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Update a segment
    """
    segment = db.query(Segment).filter(
        Segment.id == segment_id,
        Segment.company_id == current_user.company_id
    ).first()

    if not segment:
        raise HTTPException(status_code=404, detail="Segment not found")

    update_data = segment_data.model_dump(exclude_unset=True)

    # Handle criteria separately
    if 'criteria' in update_data and update_data['criteria']:
        update_data['criteria'] = update_data['criteria'].model_dump() if hasattr(update_data['criteria'], 'model_dump') else update_data['criteria']

    # Handle segment_type
    if 'segment_type' in update_data and update_data['segment_type']:
        update_data['segment_type'] = SegmentType(update_data['segment_type'])

    for field, value in update_data.items():
        setattr(segment, field, value)

    # Recalculate counts
    contact_count, lead_count = count_segment_members(db, segment, current_user.company_id)
    segment.contact_count = contact_count
    segment.lead_count = lead_count
    segment.last_refreshed_at = datetime.utcnow()

    db.commit()
    db.refresh(segment)
    return segment


@router.delete("/{segment_id}")
def delete_segment(
    segment_id: int,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Delete a segment
    """
    segment = db.query(Segment).filter(
        Segment.id == segment_id,
        Segment.company_id == current_user.company_id
    ).first()

    if not segment:
        raise HTTPException(status_code=404, detail="Segment not found")

    db.delete(segment)
    db.commit()
    return {"message": "Segment deleted successfully"}


@router.get("/{segment_id}/preview", response_model=schemas_segment.SegmentPreview)
def preview_segment(
    segment_id: int,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Preview the count of contacts/leads matching segment criteria
    """
    segment = db.query(Segment).filter(
        Segment.id == segment_id,
        Segment.company_id == current_user.company_id
    ).first()

    if not segment:
        raise HTTPException(status_code=404, detail="Segment not found")

    contact_count, lead_count = count_segment_members(db, segment, current_user.company_id)

    return schemas_segment.SegmentPreview(
        contact_count=contact_count,
        lead_count=lead_count,
        total_count=contact_count + lead_count
    )


@router.post("/preview", response_model=schemas_segment.SegmentPreview)
def preview_criteria(
    criteria: schemas_segment.SegmentCriteria,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Preview count for criteria without saving a segment
    """
    # Create a temporary segment object for counting
    temp_segment = Segment(
        name="temp",
        segment_type=SegmentType.DYNAMIC,
        criteria=criteria.model_dump(),
        company_id=current_user.company_id
    )

    contact_count, lead_count = count_segment_members(db, temp_segment, current_user.company_id)

    return schemas_segment.SegmentPreview(
        contact_count=contact_count,
        lead_count=lead_count,
        total_count=contact_count + lead_count
    )


@router.get("/{segment_id}/members", response_model=schemas_segment.SegmentMemberList)
def get_segment_members_list(
    segment_id: int,
    page: int = 1,
    page_size: int = 50,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Get paginated list of segment members
    """
    segment = db.query(Segment).filter(
        Segment.id == segment_id,
        Segment.company_id == current_user.company_id
    ).first()

    if not segment:
        raise HTTPException(status_code=404, detail="Segment not found")

    contacts, leads = get_segment_members(db, segment, current_user.company_id)

    # Combine and convert to member objects
    members = []

    for contact in contacts:
        members.append(schemas_segment.SegmentMember(
            id=contact.id,
            type="contact",
            name=contact.name,
            email=contact.email,
            stage=contact.lifecycle_stage.value if contact.lifecycle_stage else None,
            score=None
        ))

    for lead in leads:
        members.append(schemas_segment.SegmentMember(
            id=lead.id,
            type="lead",
            name=lead.contact.name if lead.contact else None,
            email=lead.contact.email if lead.contact else None,
            stage=lead.stage.value if lead.stage else None,
            score=lead.score
        ))

    total = len(members)
    start = (page - 1) * page_size
    end = start + page_size
    paginated_members = members[start:end]

    return schemas_segment.SegmentMemberList(
        members=paginated_members,
        total=total,
        page=page,
        page_size=page_size
    )


@router.post("/{segment_id}/refresh", response_model=schemas_segment.Segment)
def refresh_segment(
    segment_id: int,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Refresh segment member counts
    """
    segment = db.query(Segment).filter(
        Segment.id == segment_id,
        Segment.company_id == current_user.company_id
    ).first()

    if not segment:
        raise HTTPException(status_code=404, detail="Segment not found")

    contact_count, lead_count = count_segment_members(db, segment, current_user.company_id)
    segment.contact_count = contact_count
    segment.lead_count = lead_count
    segment.last_refreshed_at = datetime.utcnow()

    db.commit()
    db.refresh(segment)
    return segment
