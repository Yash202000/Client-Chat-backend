from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func, String
from typing import List, Optional, Dict, Any
from datetime import datetime
from app.models.lead import Lead, LeadStage, QualificationStatus
from app.models.lead_score import LeadScore
from app.schemas.lead import LeadCreate, LeadUpdate, LeadStageUpdate


def get_lead(db: Session, lead_id: int, company_id: int):
    """Get a single lead by ID"""
    return db.query(Lead).filter(
        Lead.id == lead_id,
        Lead.company_id == company_id
    ).first()


def get_leads(db: Session, company_id: int, skip: int = 0, limit: int = 100):
    """Get all leads for a company with pagination"""
    return db.query(Lead).filter(
        Lead.company_id == company_id
    ).order_by(Lead.updated_at.desc()).offset(skip).limit(limit).all()


def get_leads_by_stage(db: Session, company_id: int, stage: LeadStage, skip: int = 0, limit: int = 100):
    """Get leads filtered by stage"""
    return db.query(Lead).filter(
        Lead.company_id == company_id,
        Lead.stage == stage
    ).order_by(Lead.updated_at.desc()).offset(skip).limit(limit).all()


def get_leads_by_assignee(db: Session, company_id: int, assignee_id: int, skip: int = 0, limit: int = 100):
    """Get leads assigned to a specific user"""
    return db.query(Lead).filter(
        Lead.company_id == company_id,
        Lead.assignee_id == assignee_id
    ).order_by(Lead.updated_at.desc()).offset(skip).limit(limit).all()


def get_lead_by_contact(db: Session, contact_id: int, company_id: int):
    """Get lead for a specific contact"""
    return db.query(Lead).filter(
        Lead.contact_id == contact_id,
        Lead.company_id == company_id
    ).first()


def create_lead(db: Session, lead: LeadCreate, company_id: int):
    """Create a new lead"""
    db_lead = Lead(
        **lead.model_dump(),
        company_id=company_id,
        stage_changed_at=datetime.utcnow()
    )
    db.add(db_lead)
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
    """Get aggregated lead statistics for a company"""
    stats = {}

    # Count by stage
    for stage in LeadStage:
        count = db.query(func.count(Lead.id)).filter(
            Lead.company_id == company_id,
            Lead.stage == stage
        ).scalar()
        stats[f"{stage.value}_count"] = count

    # Total leads
    stats['total_leads'] = db.query(func.count(Lead.id)).filter(
        Lead.company_id == company_id
    ).scalar()

    # Average score
    avg_score = db.query(func.avg(Lead.score)).filter(
        Lead.company_id == company_id
    ).scalar()
    stats['average_score'] = float(avg_score) if avg_score else 0

    # Total deal value
    total_value = db.query(func.sum(Lead.deal_value)).filter(
        Lead.company_id == company_id,
        Lead.stage.in_([LeadStage.OPPORTUNITY, LeadStage.CUSTOMER])
    ).scalar()
    stats['total_pipeline_value'] = float(total_value) if total_value else 0

    # Won revenue
    won_revenue = db.query(func.sum(Lead.deal_value)).filter(
        Lead.company_id == company_id,
        Lead.stage == LeadStage.CUSTOMER
    ).scalar()
    stats['won_revenue'] = float(won_revenue) if won_revenue else 0

    return stats


def search_leads(
    db: Session,
    company_id: int,
    query: Optional[str] = None,
    stage: Optional[LeadStage] = None,
    assignee_id: Optional[int] = None,
    min_score: Optional[int] = None,
    max_score: Optional[int] = None,
    source: Optional[str] = None,
    qualification_status: Optional[QualificationStatus] = None,
    skip: int = 0,
    limit: int = 100
):
    """Advanced lead search with multiple filters"""
    filters = [Lead.company_id == company_id]

    if stage:
        filters.append(Lead.stage == stage)

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

    return db.query(Lead).filter(
        and_(*filters)
    ).order_by(Lead.updated_at.desc()).offset(skip).limit(limit).all()
