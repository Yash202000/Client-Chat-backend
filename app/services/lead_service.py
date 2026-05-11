from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, or_, func, String
from typing import List, Optional, Dict, Any
from datetime import datetime
from app.models.lead import Lead, LeadStage, QualificationStatus
from app.models.lead_score import LeadScore
from app.models.tag import lead_tags
from app.models.ticket_workflow import TicketWorkflow, TicketStatus, TicketTransition
from app.schemas.lead import LeadCreate, LeadUpdate, LeadStageUpdate


def _lead_query(db: Session):
    return db.query(Lead).options(
        joinedload(Lead.contact),
        joinedload(Lead.status),
        joinedload(Lead.assignee),
    )


def get_lead(db: Session, lead_id: int, company_id: int):
    return _lead_query(db).filter(Lead.id == lead_id, Lead.company_id == company_id).first()


def get_leads(db: Session, company_id: int, skip: int = 0, limit: int = 100):
    return _lead_query(db).filter(Lead.company_id == company_id).order_by(Lead.updated_at.desc()).offset(skip).limit(limit).all()


def get_leads_by_stage(db: Session, company_id: int, stage: LeadStage, skip: int = 0, limit: int = 100):
    """Get leads filtered by stage"""
    return db.query(Lead).options(
        joinedload(Lead.contact)
    ).filter(
        Lead.company_id == company_id,
        Lead.stage == stage
    ).order_by(Lead.updated_at.desc()).offset(skip).limit(limit).all()


def get_leads_by_assignee(db: Session, company_id: int, assignee_id: int, skip: int = 0, limit: int = 100):
    """Get leads assigned to a specific user"""
    return db.query(Lead).options(
        joinedload(Lead.contact)
    ).filter(
        Lead.company_id == company_id,
        Lead.assignee_id == assignee_id
    ).order_by(Lead.updated_at.desc()).offset(skip).limit(limit).all()


def get_lead_by_contact(db: Session, contact_id: int, company_id: int):
    """Get lead for a specific contact"""
    return db.query(Lead).options(
        joinedload(Lead.contact)
    ).filter(
        Lead.contact_id == contact_id,
        Lead.company_id == company_id
    ).first()


def create_lead(db: Session, lead: LeadCreate, company_id: int):
    from app.services.ticket_service import get_crm_workflow
    lead_data = lead.model_dump()
    workflow_id = lead_data.pop("workflow_id", None)
    status_id = lead_data.pop("status_id", None)

    # Auto-assign the company lead workflow if not provided
    if not workflow_id:
        wf = get_crm_workflow(db, company_id, "lead")
        if wf:
            workflow_id = wf.id
            if not status_id:
                default_s = db.query(TicketStatus).filter(
                    TicketStatus.workflow_id == wf.id, TicketStatus.is_default == True
                ).first()
                if not default_s:
                    default_s = db.query(TicketStatus).filter(
                        TicketStatus.workflow_id == wf.id
                    ).order_by(TicketStatus.position).first()
                if default_s:
                    status_id = default_s.id

    db_lead = Lead(
        **lead_data,
        company_id=company_id,
        workflow_id=workflow_id,
        status_id=status_id,
        stage_changed_at=datetime.utcnow(),
    )
    db.add(db_lead)
    db.flush()

    # Auto-assign via routing rules
    if not db_lead.assignee_id:
        from app.services.routing_service import evaluate_and_route
        evaluate_and_route(db, db_lead, "lead", company_id, trigger="on_create")

    db.commit()
    db.refresh(db_lead)
    return db_lead


def update_lead(db: Session, lead_id: int, lead: LeadUpdate, company_id: int):
    """Update an existing lead"""
    db_lead = get_lead(db, lead_id, company_id)
    if db_lead:
        update_data = lead.model_dump(exclude_unset=True)

        # Track stage changes
        if 'stage' in update_data and update_data['stage'] != db_lead.stage:
            db_lead.previous_stage = db_lead.stage
            db_lead.stage_changed_at = datetime.utcnow()

            # Auto-update close dates based on stage
            if update_data['stage'] == LeadStage.CUSTOMER and not db_lead.actual_close_date:
                db_lead.actual_close_date = datetime.utcnow()

        for key, value in update_data.items():
            setattr(db_lead, key, value)

        db.commit()
        db.refresh(db_lead)
    return db_lead


def update_lead_stage(db: Session, lead_id: int, stage_update: LeadStageUpdate, company_id: int):
    """Update lead stage with tracking"""
    db_lead = get_lead(db, lead_id, company_id)
    if db_lead:
        db_lead.previous_stage = db_lead.stage
        db_lead.stage = LeadStage(stage_update.stage)
        db_lead.stage_changed_at = datetime.utcnow()

        # Auto-update close dates and reasons
        if stage_update.stage == LeadStage.CUSTOMER:
            if not db_lead.actual_close_date:
                db_lead.actual_close_date = datetime.utcnow()
            if stage_update.reason:
                db_lead.won_reason = stage_update.reason
        elif stage_update.stage == LeadStage.LOST:
            if not db_lead.actual_close_date:
                db_lead.actual_close_date = datetime.utcnow()
            if stage_update.reason:
                db_lead.lost_reason = stage_update.reason

        db.commit()
        db.refresh(db_lead)
    return db_lead


def assign_lead(db: Session, lead_id: int, assignee_id: int, company_id: int):
    """Assign lead to a user"""
    db_lead = get_lead(db, lead_id, company_id)
    if db_lead:
        db_lead.assignee_id = assignee_id
        db.commit()
        db.refresh(db_lead)
    return db_lead


def update_lead_score(db: Session, lead_id: int, score: int, company_id: int):
    """Update lead score (0-100)"""
    db_lead = get_lead(db, lead_id, company_id)
    if db_lead:
        db_lead.score = max(0, min(100, score))  # Clamp to 0-100
        db_lead.last_scored_at = datetime.utcnow()
        db.commit()
        db.refresh(db_lead)
    return db_lead


def delete_lead(db: Session, lead_id: int, company_id: int):
    """Delete a lead"""
    db_lead = get_lead(db, lead_id, company_id)
    if db_lead:
        db.delete(db_lead)
        db.commit()
        return True
    return False


def get_lead_stats(db: Session, company_id: int) -> Dict[str, Any]:
    stats: Dict[str, Any] = {}

    # Count by workflow status (dynamic)
    status_counts = db.query(TicketStatus.name, func.count(Lead.id)).join(
        Lead, Lead.status_id == TicketStatus.id
    ).filter(Lead.company_id == company_id).group_by(TicketStatus.name).all()
    stats["by_status"] = {name: count for name, count in status_counts}

    stats["total_leads"] = db.query(func.count(Lead.id)).filter(Lead.company_id == company_id).scalar() or 0

    avg_score = db.query(func.avg(Lead.score)).filter(Lead.company_id == company_id).scalar()
    stats["avg_score"] = float(avg_score) if avg_score else 0

    total_value = db.query(func.sum(Lead.deal_value)).filter(Lead.company_id == company_id).scalar()
    stats["total_pipeline_value"] = float(total_value) if total_value else 0

    stats["qualified_count"] = db.query(func.count(Lead.id)).filter(
        Lead.company_id == company_id, Lead.qualification_status == QualificationStatus.QUALIFIED
    ).scalar() or 0
    stats["unqualified_count"] = db.query(func.count(Lead.id)).filter(
        Lead.company_id == company_id, Lead.qualification_status == QualificationStatus.UNQUALIFIED
    ).scalar() or 0

    return stats


def search_leads(
    db: Session,
    company_id: int,
    query: Optional[str] = None,
    stage: Optional[str] = None,
    status_id: Optional[int] = None,
    assignee_id: Optional[int] = None,
    min_score: Optional[int] = None,
    max_score: Optional[int] = None,
    source: Optional[str] = None,
    qualification_status: Optional[QualificationStatus] = None,
    tag_ids: Optional[List[int]] = None,
    skip: int = 0,
    limit: int = 100
):
    filters = [Lead.company_id == company_id]

    if status_id:
        filters.append(Lead.status_id == status_id)

    if assignee_id:
        filters.append(Lead.assignee_id == assignee_id)

    if min_score is not None:
        filters.append(Lead.score >= min_score)

    if max_score is not None:
        filters.append(Lead.score <= max_score)

    if source:
        filters.append(Lead.source == source)

    if qualification_status:
        filters.append(Lead.qualification_status == qualification_status)

    # Text search in notes or tags
    if query:
        filters.append(
            or_(
                Lead.notes.ilike(f"%{query}%"),
                Lead.tags.cast(String).ilike(f"%{query}%")
            )
        )

    base_query = db.query(Lead).options(
        joinedload(Lead.contact)
    ).filter(
        and_(*filters)
    )

    # Filter by tag IDs if provided
    if tag_ids:
        # Use subquery to avoid DISTINCT issues with JSON columns
        from sqlalchemy import select
        subq = select(lead_tags.c.lead_id).where(
            and_(
                lead_tags.c.lead_id == Lead.id,
                lead_tags.c.tag_id.in_(tag_ids)
            )
        ).exists()
        base_query = base_query.filter(subq)

    return base_query.order_by(Lead.updated_at.desc()).offset(skip).limit(limit).all()
