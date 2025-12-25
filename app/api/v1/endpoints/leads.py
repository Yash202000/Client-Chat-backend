from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any

from app.core.dependencies import get_db, get_current_active_user, require_permission
from app.services import lead_service, lead_qualification_service
from app.schemas import lead as schemas_lead
from app.schemas.lead_score import LeadScoreCreate
from app.models import user as models_user
from app.models.lead import LeadStage, QualificationStatus

router = APIRouter()


@router.get("/", response_model=List[schemas_lead.LeadWithContact], dependencies=[Depends(require_permission("lead:read"))])
def list_leads(
    skip: int = 0,
    limit: int = 100,
    stage: Optional[str] = None,
    assignee_id: Optional[int] = None,
    min_score: Optional[int] = None,
    max_score: Optional[int] = None,
    source: Optional[str] = None,
    qualification_status: Optional[str] = None,
    query: Optional[str] = None,
    tag_ids: Optional[List[int]] = Query(None, description="Filter by tag IDs"),
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    List leads with optional filtering
    """
    # If filters are provided, use search
    if any([stage, assignee_id, min_score, max_score, source, qualification_status, query, tag_ids]):
        leads = lead_service.search_leads(
            db=db,
            company_id=current_user.company_id,
            query=query,
            stage=LeadStage(stage) if stage else None,
            assignee_id=assignee_id,
            min_score=min_score,
            max_score=max_score,
            source=source,
            qualification_status=QualificationStatus(qualification_status) if qualification_status else None,
            tag_ids=tag_ids,
            skip=skip,
            limit=limit
        )
    else:
        leads = lead_service.get_leads(
            db=db,
            company_id=current_user.company_id,
            skip=skip,
            limit=limit
        )
    return leads


@router.get("/stats", dependencies=[Depends(require_permission("lead:read"))])
def get_lead_stats(
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Get aggregated lead statistics
    """
    return lead_service.get_lead_stats(db=db, company_id=current_user.company_id)


@router.get("/by-stage/{stage}", response_model=List[schemas_lead.LeadWithContact], dependencies=[Depends(require_permission("lead:read"))])
def list_leads_by_stage(
    stage: str,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    List leads filtered by stage
    """
    try:
        stage_enum = LeadStage(stage)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid stage: {stage}")

    return lead_service.get_leads_by_stage(
        db=db,
        company_id=current_user.company_id,
        stage=stage_enum,
        skip=skip,
        limit=limit
    )


@router.get("/by-assignee/{assignee_id}", response_model=List[schemas_lead.LeadWithContact], dependencies=[Depends(require_permission("lead:read"))])
def list_leads_by_assignee(
    assignee_id: int,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    List leads assigned to a specific user
    """
    return lead_service.get_leads_by_assignee(
        db=db,
        company_id=current_user.company_id,
        assignee_id=assignee_id,
        skip=skip,
        limit=limit
    )


@router.get("/available-contacts", dependencies=[Depends(require_permission("lead:read"))])
def get_available_contacts(
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Get contacts that don't have leads yet
    """
    from app.models.contact import Contact
    from app.models.lead import Lead

    # Get all contact IDs that already have leads
    existing_lead_contact_ids = db.query(Lead.contact_id).filter(
        Lead.company_id == current_user.company_id
    ).all()
    existing_ids = [row[0] for row in existing_lead_contact_ids if row[0] is not None]

    # Get contacts without leads
    query = db.query(Contact).filter(
        Contact.company_id == current_user.company_id
    )

    if existing_ids:
        query = query.filter(~Contact.id.in_(existing_ids))

    available_contacts = query.all()

    return available_contacts


@router.get("/{lead_id}", response_model=schemas_lead.LeadWithContact, dependencies=[Depends(require_permission("lead:read"))])
def get_lead(
    lead_id: int,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Get a specific lead by ID
    """
    lead = lead_service.get_lead(db=db, lead_id=lead_id, company_id=current_user.company_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead


@router.get("/{lead_id}/scores", dependencies=[Depends(require_permission("lead:read"))])
def get_lead_scores(
    lead_id: int,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Get detailed scoring breakdown for a lead
    """
    lead = lead_service.get_lead(db=db, lead_id=lead_id, company_id=current_user.company_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    return lead_qualification_service.get_lead_scoring_breakdown(db=db, lead_id=lead_id)


@router.post("/", response_model=schemas_lead.Lead, dependencies=[Depends(require_permission("lead:create"))])
def create_lead(
    lead: schemas_lead.LeadCreate,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Create a new lead from an existing contact
    """
    return lead_service.create_lead(
        db=db,
        lead=lead,
        company_id=current_user.company_id
    )


@router.post("/with-contact", response_model=schemas_lead.Lead, dependencies=[Depends(require_permission("lead:create"))])
def create_lead_with_contact(
    lead_data: Dict[str, Any],
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Create a new lead along with a new contact
    """
    from app.models.contact import Contact
    from app.schemas.contact import ContactCreate

    # Extract contact data
    contact_data = lead_data.get('contact', {})

    # Create contact first
    db_contact = Contact(
        **contact_data,
        company_id=current_user.company_id
    )
    db.add(db_contact)
    db.commit()
    db.refresh(db_contact)

    # Create lead with the new contact
    lead_create = schemas_lead.LeadCreate(
        contact_id=db_contact.id,
        source=lead_data.get('source'),
        deal_value=lead_data.get('deal_value'),
        notes=lead_data.get('notes')
    )

    return lead_service.create_lead(
        db=db,
        lead=lead_create,
        company_id=current_user.company_id
    )


@router.put("/{lead_id}", response_model=schemas_lead.Lead, dependencies=[Depends(require_permission("lead:update"))])
def update_lead(
    lead_id: int,
    lead: schemas_lead.LeadUpdate,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Update a lead
    """
    updated_lead = lead_service.update_lead(
        db=db,
        lead_id=lead_id,
        lead=lead,
        company_id=current_user.company_id
    )
    if not updated_lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return updated_lead


@router.put("/{lead_id}/stage", response_model=schemas_lead.Lead, dependencies=[Depends(require_permission("lead:update"))])
def update_lead_stage(
    lead_id: int,
    stage_update: schemas_lead.LeadStageUpdate,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Update lead stage with tracking
    """
    updated_lead = lead_service.update_lead_stage(
        db=db,
        lead_id=lead_id,
        stage_update=stage_update,
        company_id=current_user.company_id
    )
    if not updated_lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return updated_lead


@router.put("/{lead_id}/assign", response_model=schemas_lead.Lead, dependencies=[Depends(require_permission("lead:update"))])
def assign_lead(
    lead_id: int,
    assignment: schemas_lead.LeadAssignment,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Assign lead to a user
    """
    updated_lead = lead_service.assign_lead(
        db=db,
        lead_id=lead_id,
        assignee_id=assignment.assignee_id,
        company_id=current_user.company_id
    )
    if not updated_lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return updated_lead


@router.post("/{lead_id}/score", dependencies=[Depends(require_permission("lead:update"))])
def score_lead_manually(
    lead_id: int,
    score_value: int = Query(..., ge=0, le=100),
    reason: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Manually score a lead
    """
    lead = lead_service.get_lead(db=db, lead_id=lead_id, company_id=current_user.company_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    score = lead_qualification_service.create_manual_score(
        db=db,
        lead_id=lead_id,
        score_value=score_value,
        user_id=current_user.id,
        reason=reason
    )

    # Update lead's overall score
    lead_service.update_lead_score(db=db, lead_id=lead_id, score=score_value, company_id=current_user.company_id)

    return {"success": True, "score": score_value}


@router.post("/{lead_id}/qualify", dependencies=[Depends(require_permission("lead:update"))])
def auto_qualify_lead(
    lead_id: int,
    min_score_threshold: int = Query(70, ge=0, le=100),
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Automatically qualify lead based on AI and engagement scoring
    """
    lead = lead_service.get_lead(db=db, lead_id=lead_id, company_id=current_user.company_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    qualified_lead = lead_qualification_service.auto_qualify_lead(
        db=db,
        lead_id=lead_id,
        min_score_threshold=min_score_threshold
    )

    return {
        "success": True,
        "lead_id": lead_id,
        "score": qualified_lead.score,
        "qualification_status": qualified_lead.qualification_status.value,
        "stage": qualified_lead.stage.value
    }


@router.delete("/{lead_id}", dependencies=[Depends(require_permission("lead:delete"))])
def delete_lead(
    lead_id: int,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Delete a lead
    """
    success = lead_service.delete_lead(
        db=db,
        lead_id=lead_id,
        company_id=current_user.company_id
    )
    if not success:
        raise HTTPException(status_code=404, detail="Lead not found")
    return {"success": True}


@router.get("/by-stage/{stage}", response_model=List[schemas_lead.LeadWithContact], dependencies=[Depends(require_permission("lead:read"))])
def get_leads_by_stage(
    stage: str,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Get all leads in a specific stage
    """
    leads = lead_service.search_leads(
        db=db,
        company_id=current_user.company_id,
        stage=LeadStage(stage),
        skip=skip,
        limit=limit
    )
    return leads


@router.get("/by-assignee/{assignee_id}", response_model=List[schemas_lead.LeadWithContact], dependencies=[Depends(require_permission("lead:read"))])
def get_leads_by_assignee(
    assignee_id: int,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Get all leads assigned to a specific user
    """
    leads = lead_service.search_leads(
        db=db,
        company_id=current_user.company_id,
        assignee_id=assignee_id,
        skip=skip,
        limit=limit
    )
    return leads


@router.get("/high-value", response_model=List[schemas_lead.LeadWithContact], dependencies=[Depends(require_permission("lead:read"))])
def get_high_value_leads(
    min_deal_value: float = Query(10000, description="Minimum deal value"),
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Get high-value leads above a certain deal value threshold
    """
    from app.models.lead import Lead
    from sqlalchemy import and_

    leads = db.query(Lead).filter(
        and_(
            Lead.company_id == current_user.company_id,
            Lead.deal_value >= min_deal_value
        )
    ).order_by(Lead.deal_value.desc()).offset(skip).limit(limit).all()

    return leads


@router.get("/unassigned", response_model=List[schemas_lead.LeadWithContact], dependencies=[Depends(require_permission("lead:read"))])
def get_unassigned_leads(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Get all unassigned leads
    """
    from app.models.lead import Lead

    leads = db.query(Lead).filter(
        Lead.company_id == current_user.company_id,
        Lead.assignee_id.is_(None)
    ).order_by(Lead.score.desc()).offset(skip).limit(limit).all()

    return leads


@router.post("/bulk-assign", dependencies=[Depends(require_permission("lead:update"))])
def bulk_assign_leads(
    lead_ids: List[int],
    assignee_id: int,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Assign multiple leads to a user at once
    """
    updated_count = 0
    for lead_id in lead_ids:
        lead = lead_service.assign_lead(
            db=db,
            lead_id=lead_id,
            assignee_id=assignee_id,
            company_id=current_user.company_id
        )
        if lead:
            updated_count += 1

    return {
        "success": True,
        "updated_count": updated_count,
        "total_requested": len(lead_ids)
    }


@router.post("/bulk-update-stage", dependencies=[Depends(require_permission("lead:update"))])
def bulk_update_stage(
    lead_ids: List[int],
    stage: str,
    stage_reason: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Update stage for multiple leads at once
    """
    from app.schemas.lead import LeadStageUpdate

    stage_update = LeadStageUpdate(
        stage=LeadStage(stage),
        stage_reason=stage_reason
    )

    updated_count = 0
    for lead_id in lead_ids:
        lead = lead_service.update_lead_stage(
            db=db,
            lead_id=lead_id,
            stage_update=stage_update,
            company_id=current_user.company_id
        )
        if lead:
            updated_count += 1

    return {
        "success": True,
        "updated_count": updated_count,
        "total_requested": len(lead_ids)
    }
