from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func
from typing import List, Optional, Dict, Any
from datetime import datetime
from app.models.campaign import Campaign, CampaignStatus, CampaignType
from app.models.campaign_contact import CampaignContact, EnrollmentStatus
from app.models.campaign_message import CampaignMessage
from app.models.contact import Contact, LifecycleStage
from app.models.lead import Lead, LeadStage
from app.schemas.campaign import CampaignCreate, CampaignUpdate


def get_campaign(db: Session, campaign_id: int, company_id: int):
    """Get a single campaign by ID"""
    return db.query(Campaign).filter(
        Campaign.id == campaign_id,
        Campaign.company_id == company_id
    ).first()


def get_campaigns(db: Session, company_id: int, skip: int = 0, limit: int = 100):
    """Get all campaigns for a company with pagination"""
    return db.query(Campaign).filter(
        Campaign.company_id == company_id
    ).order_by(Campaign.updated_at.desc()).offset(skip).limit(limit).all()


def get_campaigns_by_status(db: Session, company_id: int, status: CampaignStatus, skip: int = 0, limit: int = 100):
    """Get campaigns filtered by status"""
    return db.query(Campaign).filter(
        Campaign.company_id == company_id,
        Campaign.status == status
    ).order_by(Campaign.updated_at.desc()).offset(skip).limit(limit).all()


def get_campaigns_by_type(db: Session, company_id: int, campaign_type: CampaignType, skip: int = 0, limit: int = 100):
    """Get campaigns filtered by type"""
    return db.query(Campaign).filter(
        Campaign.company_id == company_id,
        Campaign.campaign_type == campaign_type
    ).order_by(Campaign.updated_at.desc()).offset(skip).limit(limit).all()


def create_campaign(db: Session, campaign: CampaignCreate, company_id: int, created_by_user_id: int):
    """Create a new campaign"""
    db_campaign = Campaign(
        **campaign.model_dump(exclude={'owner_user_id'}),
        company_id=company_id,
        created_by_user_id=created_by_user_id,
        owner_user_id=campaign.owner_user_id or created_by_user_id
    )
    db.add(db_campaign)
    db.commit()
    db.refresh(db_campaign)
    return db_campaign


def update_campaign(db: Session, campaign_id: int, campaign: CampaignUpdate, company_id: int):
    """Update an existing campaign"""
    db_campaign = get_campaign(db, campaign_id, company_id)
    if db_campaign:
        update_data = campaign.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(db_campaign, key, value)
        db.commit()
        db.refresh(db_campaign)
    return db_campaign


def update_campaign_status(db: Session, campaign_id: int, status: CampaignStatus, company_id: int):
    """Update campaign status"""
    db_campaign = get_campaign(db, campaign_id, company_id)
    if db_campaign:
        db_campaign.status = status
        if status == CampaignStatus.ACTIVE and not db_campaign.start_date:
            db_campaign.start_date = datetime.utcnow()
        elif status == CampaignStatus.COMPLETED and not db_campaign.end_date:
            db_campaign.end_date = datetime.utcnow()
        db.commit()
        db.refresh(db_campaign)
    return db_campaign


def delete_campaign(db: Session, campaign_id: int, company_id: int):
    """Delete a campaign"""
    db_campaign = get_campaign(db, campaign_id, company_id)
    if db_campaign:
        db.delete(db_campaign)
        db.commit()
        return True
    return False


def get_targeted_contacts(db: Session, campaign_id: int, company_id: int) -> List[Contact]:
    """
    Get contacts that match the campaign's target criteria.
    This implements the contact targeting logic based on the campaign's target_criteria JSONB field.
    """
    campaign = get_campaign(db, campaign_id, company_id)
    if not campaign or not campaign.target_criteria:
        return []

    criteria = campaign.target_criteria
    query = db.query(Contact).filter(Contact.company_id == company_id)
    lead_joined = False  # Track if we've already joined the Lead table

    # Filter by lifecycle stage
    if 'lifecycle_stages' in criteria:
        stages = [LifecycleStage(s) for s in criteria['lifecycle_stages']]
        query = query.filter(Contact.lifecycle_stage.in_(stages))

    # Filter by lead source
    if 'lead_sources' in criteria:
        query = query.filter(Contact.lead_source.in_(criteria['lead_sources']))

    # Filter by opt-in status
    if 'opt_in_status' in criteria:
        query = query.filter(Contact.opt_in_status == criteria['opt_in_status'])

    # Exclude do-not-contact
    if criteria.get('exclude_do_not_contact', True):
        query = query.filter(Contact.do_not_contact == False)

    # Filter by lead score (requires join with Lead table)
    if 'min_lead_score' in criteria or 'max_lead_score' in criteria:
        if not lead_joined:
            query = query.join(Lead, Contact.id == Lead.contact_id)
            lead_joined = True
        if 'min_lead_score' in criteria:
            query = query.filter(Lead.score >= criteria['min_lead_score'])
        if 'max_lead_score' in criteria:
            query = query.filter(Lead.score <= criteria['max_lead_score'])

    # Filter by lead stage
    if 'lead_stages' in criteria:
        if not lead_joined:
            query = query.join(Lead, Contact.id == Lead.contact_id)
            lead_joined = True
        stages = [LeadStage(s) for s in criteria['lead_stages']]
        query = query.filter(Lead.stage.in_(stages))

    # Filter by tags (JSON array contains check)
    if 'tags' in criteria and criteria['tags']:
        if not lead_joined:
            query = query.join(Lead, Contact.id == Lead.contact_id)
            lead_joined = True
        for tag in criteria['tags']:
            query = query.filter(Lead.tags.contains([tag]))

    # Exclude contacts already in this campaign
    if criteria.get('exclude_already_enrolled', True):
        enrolled_contact_ids = db.query(CampaignContact.contact_id).filter(
            CampaignContact.campaign_id == campaign_id
        ).subquery()
        query = query.filter(~Contact.id.in_(enrolled_contact_ids))

    # Limit results
    max_contacts = criteria.get('max_contacts', 10000)
    return query.limit(max_contacts).all()


def enroll_contacts(
    db: Session,
    campaign_id: int,
    contact_ids: List[int],
    company_id: int,
    enrolled_by_user_id: Optional[int] = None,
    enrollment_data: Optional[Dict[str, Any]] = None
) -> List[CampaignContact]:
    """
    Enroll contacts in a campaign
    """
    campaign = get_campaign(db, campaign_id, company_id)
    if not campaign:
        return []

    enrolled = []
    for contact_id in contact_ids:
        # Check if already enrolled
        existing = db.query(CampaignContact).filter(
            CampaignContact.campaign_id == campaign_id,
            CampaignContact.contact_id == contact_id
        ).first()

        if not existing:
            # Get lead for this contact if exists
            lead = db.query(Lead).filter(
                Lead.contact_id == contact_id,
                Lead.company_id == company_id
            ).first()

            enrollment = CampaignContact(
                campaign_id=campaign_id,
                contact_id=contact_id,
                lead_id=lead.id if lead else None,
                enrolled_by_user_id=enrolled_by_user_id,
                enrollment_data=enrollment_data
            )
            db.add(enrollment)
            enrolled.append(enrollment)

    if enrolled:
        # Update campaign total contacts
        campaign.total_contacts = db.query(func.count(CampaignContact.id)).filter(
            CampaignContact.campaign_id == campaign_id
        ).scalar()
        db.commit()

        for enrollment in enrolled:
            db.refresh(enrollment)

    return enrolled


def unenroll_contact(db: Session, campaign_id: int, contact_id: int, company_id: int, reason: Optional[str] = None):
    """Unenroll a contact from a campaign"""
    enrollment = db.query(CampaignContact).join(Campaign).filter(
        CampaignContact.campaign_id == campaign_id,
        CampaignContact.contact_id == contact_id,
        Campaign.company_id == company_id
    ).first()

    if enrollment:
        enrollment.status = EnrollmentStatus.OPTED_OUT
        enrollment.opted_out_at = datetime.utcnow()
        enrollment.opt_out_reason = reason
        db.commit()
        db.refresh(enrollment)

    return enrollment


def get_campaign_contacts(db: Session, campaign_id: int, company_id: int, status: Optional[EnrollmentStatus] = None, skip: int = 0, limit: int = 100):
    """Get contacts enrolled in a campaign"""
    query = db.query(CampaignContact).join(Campaign).filter(
        CampaignContact.campaign_id == campaign_id,
        Campaign.company_id == company_id
    )

    if status:
        query = query.filter(CampaignContact.status == status)

    return query.offset(skip).limit(limit).all()


def update_campaign_metrics(db: Session, campaign_id: int, company_id: int):
    """
    Recalculate and update campaign metrics from activities and enrollments
    """
    campaign = get_campaign(db, campaign_id, company_id)
    if not campaign:
        return None

    # Count enrollments by status
    total_contacts = db.query(func.count(CampaignContact.id)).filter(
        CampaignContact.campaign_id == campaign_id
    ).scalar()

    # Count contacts reached (at least one message sent)
    contacts_reached = db.query(func.count(func.distinct(CampaignContact.contact_id))).filter(
        CampaignContact.campaign_id == campaign_id,
        CampaignContact.current_step > 0
    ).scalar()

    # Count engaged (opened, clicked, or replied)
    contacts_engaged = db.query(func.count(func.distinct(CampaignContact.contact_id))).filter(
        CampaignContact.campaign_id == campaign_id,
        or_(
            CampaignContact.opens > 0,
            CampaignContact.clicks > 0,
            CampaignContact.replies > 0
        )
    ).scalar()

    # Count converted
    contacts_converted = db.query(func.count(CampaignContact.id)).filter(
        CampaignContact.campaign_id == campaign_id,
        CampaignContact.conversions > 0
    ).scalar()

    # Sum revenue from activities
    from app.models.campaign_activity import CampaignActivity
    total_revenue = db.query(func.sum(CampaignActivity.revenue_amount)).filter(
        CampaignActivity.campaign_id == campaign_id
    ).scalar()

    # Update campaign
    campaign.total_contacts = total_contacts or 0
    campaign.contacts_reached = contacts_reached or 0
    campaign.contacts_engaged = contacts_engaged or 0
    campaign.contacts_converted = contacts_converted or 0
    campaign.total_revenue = total_revenue or 0

    db.commit()
    db.refresh(campaign)
    return campaign
