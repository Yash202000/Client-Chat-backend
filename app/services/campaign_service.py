from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func
from typing import List, Optional, Dict, Any
from datetime import datetime
from app.models.campaign import Campaign, CampaignStatus, CampaignType
from app.models.campaign_contact import CampaignContact, EnrollmentStatus
from app.models.campaign_message import CampaignMessage
from app.models.contact import Contact, LifecycleStage
from app.models.lead import Lead, LeadStage
from app.models.segment import Segment, SegmentType
from app.models.tag import Tag, lead_tags, contact_tags
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
    Get contacts that match the campaign's target criteria or segment.
    Supports:
    1. Segment-based targeting (segment_id on campaign)
    2. Criteria-based targeting (target_criteria JSONB field)
    3. Manual selection (contact_ids/lead_ids in target_criteria)
    """
    print(f"[TARGET] Getting targeted contacts for campaign {campaign_id}")

    campaign = get_campaign(db, campaign_id, company_id)
    if not campaign:
        print(f"[TARGET] Campaign {campaign_id} not found")
        return []

    print(f"[TARGET] Campaign: {campaign.name}, segment_id: {campaign.segment_id}, target_criteria: {campaign.target_criteria}")

    # Priority 1: If campaign has a segment_id, use segment-based targeting
    if campaign.segment_id:
        print(f"[TARGET] Using segment-based targeting with segment_id: {campaign.segment_id}")
        return get_contacts_from_segment(db, campaign.segment_id, company_id, campaign_id)

    # Priority 2: Check target_criteria
    if not campaign.target_criteria:
        return []

    criteria = campaign.target_criteria
    print(f"[TARGET] Criteria type: {type(criteria)}, value: {criteria}")

    # Handle manual selection
    if criteria.get('manual_selection'):
        contact_ids = criteria.get('contact_ids', [])
        lead_ids = criteria.get('lead_ids', [])
        print(f"[TARGET] Manual selection - contact_ids: {contact_ids}, lead_ids: {lead_ids}")

        contacts = []
        if contact_ids:
            contacts = db.query(Contact).filter(
                Contact.id.in_(contact_ids),
                Contact.company_id == company_id
            ).all()
            print(f"[TARGET] Found {len(contacts)} contacts from contact_ids")

        # Also get contacts from leads
        if lead_ids:
            lead_contacts = db.query(Contact).join(
                Lead, Contact.id == Lead.contact_id
            ).filter(
                Lead.id.in_(lead_ids),
                Contact.company_id == company_id
            ).all()
            print(f"[TARGET] Found {len(lead_contacts)} contacts from lead_ids")
            # Merge without duplicates
            existing_ids = {c.id for c in contacts}
            for lc in lead_contacts:
                if lc.id not in existing_ids:
                    contacts.append(lc)

        print(f"[TARGET] Returning {len(contacts)} total contacts for manual selection")
        return contacts

    # Standard criteria-based targeting
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
        statuses = criteria['opt_in_status']
        if isinstance(statuses, list):
            query = query.filter(Contact.opt_in_status.in_(statuses))
        else:
            query = query.filter(Contact.opt_in_status == statuses)

    # Exclude do-not-contact
    if criteria.get('exclude_do_not_contact', True):
        query = query.filter(Contact.do_not_contact == False)

    # Filter by lead score (requires join with Lead table)
    if 'score_min' in criteria or 'score_max' in criteria or 'min_lead_score' in criteria or 'max_lead_score' in criteria:
        if not lead_joined:
            query = query.join(Lead, Contact.id == Lead.contact_id)
            lead_joined = True
        min_score = criteria.get('score_min') or criteria.get('min_lead_score')
        max_score = criteria.get('score_max') or criteria.get('max_lead_score')
        if min_score is not None:
            query = query.filter(Lead.score >= min_score)
        if max_score is not None:
            query = query.filter(Lead.score <= max_score)

    # Filter by lead stage
    if 'lead_stages' in criteria:
        if not lead_joined:
            query = query.join(Lead, Contact.id == Lead.contact_id)
            lead_joined = True
        stages = [LeadStage(s) for s in criteria['lead_stages']]
        query = query.filter(Lead.stage.in_(stages))

    # Filter by tag IDs (new format using tag association tables)
    if 'tag_ids' in criteria and criteria['tag_ids']:
        tag_ids = criteria['tag_ids']
        # Get contacts with any of the specified tags
        tagged_contact_ids = db.query(contact_tags.c.contact_id).filter(
            contact_tags.c.tag_id.in_(tag_ids)
        ).distinct().subquery()
        query = query.filter(Contact.id.in_(tagged_contact_ids))

    # Legacy: Filter by tags (JSON array contains check)
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


def get_contacts_from_segment(db: Session, segment_id: int, company_id: int, campaign_id: int = None) -> List[Contact]:
    """
    Get contacts from a segment (dynamic or static).
    """
    print(f"[SEGMENT] Getting contacts from segment {segment_id} for company {company_id}")

    segment = db.query(Segment).filter(
        Segment.id == segment_id,
        Segment.company_id == company_id
    ).first()

    if not segment:
        print(f"[SEGMENT] Segment {segment_id} not found")
        return []

    print(f"[SEGMENT] Found segment: {segment.name}, type: {segment.segment_type}, criteria: {segment.criteria}")

    contacts = []

    # Handle static segments
    if segment.segment_type == SegmentType.STATIC:
        print(f"[SEGMENT] Static segment - contact_ids: {segment.static_contact_ids}, lead_ids: {segment.static_lead_ids}")
        contact_ids = segment.static_contact_ids or []
        lead_ids = segment.static_lead_ids or []

        if contact_ids:
            contacts = db.query(Contact).filter(
                Contact.id.in_(contact_ids),
                Contact.company_id == company_id
            ).all()

        if lead_ids:
            lead_contacts = db.query(Contact).join(
                Lead, Contact.id == Lead.contact_id
            ).filter(
                Lead.id.in_(lead_ids),
                Contact.company_id == company_id
            ).all()
            existing_ids = {c.id for c in contacts}
            for lc in lead_contacts:
                if lc.id not in existing_ids:
                    contacts.append(lc)

    # Handle dynamic segments
    elif segment.segment_type == SegmentType.DYNAMIC and segment.criteria:
        criteria = segment.criteria
        query = db.query(Contact).filter(Contact.company_id == company_id)
        lead_joined = False

        # Include contacts filter
        include_contacts = criteria.get('include_contacts', True)
        include_leads = criteria.get('include_leads', True)

        if not include_contacts and include_leads:
            # Only get contacts that have leads
            query = query.join(Lead, Contact.id == Lead.contact_id)
            lead_joined = True

        # Filter by lifecycle stages
        if 'lifecycle_stages' in criteria and criteria['lifecycle_stages']:
            stages = [LifecycleStage(s) for s in criteria['lifecycle_stages']]
            query = query.filter(Contact.lifecycle_stage.in_(stages))

        # Filter by lead sources
        if 'lead_sources' in criteria and criteria['lead_sources']:
            query = query.filter(Contact.lead_source.in_(criteria['lead_sources']))

        # Filter by opt-in status
        if 'opt_in_status' in criteria and criteria['opt_in_status']:
            query = query.filter(Contact.opt_in_status.in_(criteria['opt_in_status']))

        # Filter by lead stages
        if 'lead_stages' in criteria and criteria['lead_stages']:
            if not lead_joined:
                query = query.join(Lead, Contact.id == Lead.contact_id)
                lead_joined = True
            stages = [LeadStage(s) for s in criteria['lead_stages']]
            query = query.filter(Lead.stage.in_(stages))

        # Filter by lead score range
        if criteria.get('score_min') is not None or criteria.get('score_max') is not None:
            if not lead_joined:
                query = query.join(Lead, Contact.id == Lead.contact_id)
                lead_joined = True
            if criteria.get('score_min') is not None:
                query = query.filter(Lead.score >= criteria['score_min'])
            if criteria.get('score_max') is not None:
                query = query.filter(Lead.score <= criteria['score_max'])

        # Filter by tag IDs
        if 'tag_ids' in criteria and criteria['tag_ids']:
            tag_ids = criteria['tag_ids']
            tagged_contact_ids = db.query(contact_tags.c.contact_id).filter(
                contact_tags.c.tag_id.in_(tag_ids)
            ).distinct().subquery()
            query = query.filter(Contact.id.in_(tagged_contact_ids))

        # Exclude do-not-contact
        query = query.filter(Contact.do_not_contact == False)

        contacts = query.all()
        print(f"[SEGMENT] Dynamic segment query returned {len(contacts)} contacts")

    print(f"[SEGMENT] Total contacts before exclusion: {len(contacts)}")

    # Exclude contacts already enrolled in the campaign (if campaign_id provided)
    if campaign_id and contacts:
        enrolled_ids = set(
            row[0] for row in db.query(CampaignContact.contact_id).filter(
                CampaignContact.campaign_id == campaign_id
            ).all()
        )
        print(f"[SEGMENT] Already enrolled contact IDs: {enrolled_ids}")
        contacts = [c for c in contacts if c.id not in enrolled_ids]

    print(f"[SEGMENT] Final contacts to enroll: {len(contacts)}")
    return contacts


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
    Recalculate and update campaign metrics from activities and enrollments.
    Also checks if campaign should be marked as completed.
    """
    from datetime import datetime, timezone
    from app.models.campaign_contact import EnrollmentStatus

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

    # Update campaign metrics
    campaign.total_contacts = total_contacts or 0
    campaign.contacts_reached = contacts_reached or 0
    campaign.contacts_engaged = contacts_engaged or 0
    campaign.contacts_converted = contacts_converted or 0
    campaign.total_revenue = total_revenue or 0

    # Check if campaign should be marked as completed
    # Campaign is completed when all enrollments are either completed or failed (none active/pending)
    if campaign.status == CampaignStatus.ACTIVE and total_contacts > 0:
        active_or_pending = db.query(func.count(CampaignContact.id)).filter(
            CampaignContact.campaign_id == campaign_id,
            CampaignContact.status.in_([EnrollmentStatus.ACTIVE, EnrollmentStatus.PENDING])
        ).scalar()

        completed_enrollments = db.query(func.count(CampaignContact.id)).filter(
            CampaignContact.campaign_id == campaign_id,
            CampaignContact.status == EnrollmentStatus.COMPLETED
        ).scalar()

        print(f"[CAMPAIGN METRICS] Campaign {campaign_id}: total={total_contacts}, active/pending={active_or_pending}, completed={completed_enrollments}")

        if active_or_pending == 0:
            # All enrollments are done (completed or failed)
            campaign.status = CampaignStatus.COMPLETED
            if not campaign.end_date:
                campaign.end_date = datetime.now(timezone.utc).replace(tzinfo=None)
            print(f"[CAMPAIGN METRICS] Campaign {campaign_id} marked as COMPLETED")

    db.commit()
    db.refresh(campaign)
    return campaign
