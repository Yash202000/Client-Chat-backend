from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from typing import List, Optional

from app.core.dependencies import get_db, get_current_active_user
from app.services import campaign_service, campaign_execution_service, campaign_analytics_service
from app.schemas import campaign as schemas_campaign
from app.schemas.campaign_message import CampaignMessageCreate, CampaignMessageUpdate, CampaignMessage
from app.schemas.campaign_contact import CampaignContactCreate, CampaignContact
from app.models import user as models_user
from app.models import campaign as models_campaign
from app.models.campaign import CampaignStatus, CampaignType
from app.models.campaign_contact import EnrollmentStatus

router = APIRouter()


# Campaign CRUD


@router.get("/", response_model=List[schemas_campaign.Campaign])
def list_campaigns(
    skip: int = 0,
    limit: int = 100,
    status: Optional[str] = None,
    campaign_type: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    List all campaigns with optional filtering
    """
    if status:
        try:
            status_enum = CampaignStatus(status)
            campaigns = campaign_service.get_campaigns_by_status(
                db=db,
                company_id=current_user.company_id,
                status=status_enum,
                skip=skip,
                limit=limit
            )
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")
    elif campaign_type:
        try:
            type_enum = CampaignType(campaign_type)
            campaigns = campaign_service.get_campaigns_by_type(
                db=db,
                company_id=current_user.company_id,
                campaign_type=type_enum,
                skip=skip,
                limit=limit
            )
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid campaign type: {campaign_type}")
    else:
        campaigns = campaign_service.get_campaigns(
            db=db,
            company_id=current_user.company_id,
            skip=skip,
            limit=limit
        )
    return campaigns


@router.get("/active", response_model=List[schemas_campaign.Campaign])
def get_active_campaigns(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Get all currently active campaigns
    """
    campaigns = db.query(models_campaign.Campaign).filter(
        models_campaign.Campaign.company_id == current_user.company_id,
        models_campaign.Campaign.status == CampaignStatus.ACTIVE
    ).order_by(models_campaign.Campaign.start_date.desc()).offset(skip).limit(limit).all()

    return campaigns


@router.get("/{campaign_id}", response_model=schemas_campaign.Campaign)
def get_campaign(
    campaign_id: int,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Get a specific campaign by ID
    """
    campaign = campaign_service.get_campaign(
        db=db,
        campaign_id=campaign_id,
        company_id=current_user.company_id
    )
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return campaign


@router.post("/", response_model=schemas_campaign.Campaign)
def create_campaign(
    campaign: schemas_campaign.CampaignCreate,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Create a new campaign
    """
    return campaign_service.create_campaign(
        db=db,
        campaign=campaign,
        company_id=current_user.company_id,
        created_by_user_id=current_user.id
    )


@router.put("/{campaign_id}", response_model=schemas_campaign.Campaign)
def update_campaign(
    campaign_id: int,
    campaign: schemas_campaign.CampaignUpdate,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Update a campaign
    """
    updated = campaign_service.update_campaign(
        db=db,
        campaign_id=campaign_id,
        campaign=campaign,
        company_id=current_user.company_id
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return updated


@router.delete("/{campaign_id}")
def delete_campaign(
    campaign_id: int,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Delete a campaign
    """
    success = campaign_service.delete_campaign(
        db=db,
        campaign_id=campaign_id,
        company_id=current_user.company_id
    )
    if not success:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return {"success": True}


# Campaign Messages


@router.get("/{campaign_id}/messages", response_model=List[CampaignMessage])
def list_campaign_messages(
    campaign_id: int,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    List all messages for a campaign
    """
    campaign = campaign_service.get_campaign(db=db, campaign_id=campaign_id, company_id=current_user.company_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return campaign.messages


@router.post("/{campaign_id}/messages", response_model=CampaignMessage)
def create_campaign_message(
    campaign_id: int,
    message: CampaignMessageCreate,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Add a message to a campaign sequence
    """
    from app.models.campaign_message import CampaignMessage as CampaignMessageModel

    campaign = campaign_service.get_campaign(db=db, campaign_id=campaign_id, company_id=current_user.company_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    db_message = CampaignMessageModel(**message.model_dump())
    db.add(db_message)
    db.commit()
    db.refresh(db_message)
    return db_message


@router.put("/{campaign_id}/messages/{message_id}", response_model=CampaignMessage)
def update_campaign_message(
    campaign_id: int,
    message_id: int,
    message: CampaignMessageUpdate,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Update a campaign message
    """
    from app.models.campaign_message import CampaignMessage as CampaignMessageModel

    # Verify campaign belongs to user's company
    campaign = campaign_service.get_campaign(db=db, campaign_id=campaign_id, company_id=current_user.company_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    # Get the message
    db_message = db.query(CampaignMessageModel).filter(
        CampaignMessageModel.id == message_id,
        CampaignMessageModel.campaign_id == campaign_id
    ).first()

    if not db_message:
        raise HTTPException(status_code=404, detail="Campaign message not found")

    # Update the message
    update_data = message.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_message, field, value)

    db.commit()
    db.refresh(db_message)
    return db_message


@router.delete("/{campaign_id}/messages/{message_id}")
def delete_campaign_message(
    campaign_id: int,
    message_id: int,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Delete a campaign message
    """
    from app.models.campaign_message import CampaignMessage as CampaignMessageModel

    # Verify campaign belongs to user's company
    campaign = campaign_service.get_campaign(db=db, campaign_id=campaign_id, company_id=current_user.company_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    # Get the message
    db_message = db.query(CampaignMessageModel).filter(
        CampaignMessageModel.id == message_id,
        CampaignMessageModel.campaign_id == campaign_id
    ).first()

    if not db_message:
        raise HTTPException(status_code=404, detail="Campaign message not found")

    db.delete(db_message)
    db.commit()
    return {"status": "deleted"}


# Campaign Contacts/Enrollment


@router.get("/{campaign_id}/contacts", response_model=List[CampaignContact])
def list_campaign_contacts(
    campaign_id: int,
    status: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    List contacts enrolled in a campaign
    """
    status_enum = None
    if status:
        try:
            status_enum = EnrollmentStatus(status)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")

    return campaign_service.get_campaign_contacts(
        db=db,
        campaign_id=campaign_id,
        company_id=current_user.company_id,
        status=status_enum,
        skip=skip,
        limit=limit
    )


@router.post("/{campaign_id}/enroll")
def enroll_contacts_in_campaign(
    campaign_id: int,
    enrollment_request: schemas_campaign.CampaignEnrollmentRequest,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Enroll contacts in a campaign
    """
    campaign = campaign_service.get_campaign(db=db, campaign_id=campaign_id, company_id=current_user.company_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    enrolled = campaign_service.enroll_contacts(
        db=db,
        campaign_id=campaign_id,
        contact_ids=enrollment_request.contact_ids,
        company_id=current_user.company_id,
        enrolled_by_user_id=current_user.id,
        enrollment_data=enrollment_request.enrollment_data
    )

    return {
        "success": True,
        "enrolled_count": len(enrolled),
        "enrollments": [{"contact_id": e.contact_id, "id": e.id} for e in enrolled]
    }


@router.post("/{campaign_id}/enroll-from-criteria")
def enroll_from_targeting_criteria(
    campaign_id: int,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Automatically enroll contacts based on campaign's target criteria
    """
    from app.models.campaign_contact import CampaignContact as CampaignContactModel

    campaign = campaign_service.get_campaign(db=db, campaign_id=campaign_id, company_id=current_user.company_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    print(f"[ENROLL] Campaign {campaign_id}: segment_id={campaign.segment_id}, target_criteria={campaign.target_criteria}")

    # Get targeted contacts
    targeted_contacts = campaign_service.get_targeted_contacts(
        db=db,
        campaign_id=campaign_id,
        company_id=current_user.company_id
    )

    print(f"[ENROLL] Found {len(targeted_contacts) if targeted_contacts else 0} targeted contacts")

    if not targeted_contacts:
        # Check if there are existing enrollments
        existing_count = db.query(CampaignContactModel).filter(
            CampaignContactModel.campaign_id == campaign_id
        ).count()
        return {
            "success": True,
            "enrolled_count": 0,
            "existing_count": existing_count,
            "message": "No contacts match targeting criteria"
        }

    # Enroll them
    contact_ids = [c.id for c in targeted_contacts]
    print(f"[ENROLL] Enrolling contact IDs: {contact_ids}")

    enrolled = campaign_service.enroll_contacts(
        db=db,
        campaign_id=campaign_id,
        contact_ids=contact_ids,
        company_id=current_user.company_id,
        enrolled_by_user_id=current_user.id
    )

    print(f"[ENROLL] Successfully enrolled {len(enrolled)} contacts")

    # Get total enrolled (new + existing)
    total_enrolled = db.query(CampaignContactModel).filter(
        CampaignContactModel.campaign_id == campaign_id
    ).count()

    return {
        "success": True,
        "enrolled_count": len(enrolled),
        "total_enrolled": total_enrolled,
        "message": f"Enrolled {len(enrolled)} new contacts. Total: {total_enrolled}"
    }


@router.post("/{campaign_id}/contacts/{contact_id}/unenroll")
def unenroll_contact(
    campaign_id: int,
    contact_id: int,
    reason: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Unenroll a contact from a campaign
    """
    enrollment = campaign_service.unenroll_contact(
        db=db,
        campaign_id=campaign_id,
        contact_id=contact_id,
        company_id=current_user.company_id,
        reason=reason
    )

    if not enrollment:
        raise HTTPException(status_code=404, detail="Enrollment not found")

    return {"success": True}


# Campaign Execution


@router.post("/{campaign_id}/start")
async def start_campaign(
    campaign_id: int,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Start a campaign - if start_date is in the future, messages are scheduled for that time.
    If start_date is now or in the past, messages are sent immediately.
    """
    from datetime import datetime

    campaign = campaign_service.get_campaign(db=db, campaign_id=campaign_id, company_id=current_user.company_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    success = campaign_execution_service.start_campaign(
        db=db,
        campaign_id=campaign_id,
        company_id=current_user.company_id
    )

    if success:
        # Refresh campaign to get updated data
        db.refresh(campaign)

        # Only process queue immediately if start_date is now or in the past
        # Use timezone-aware UTC time for consistent comparison
        from datetime import timezone
        current_time = datetime.now(timezone.utc)

        # Normalize campaign.start_date for comparison
        campaign_start = campaign.start_date
        if campaign_start and campaign_start.tzinfo is None:
            campaign_start = campaign_start.replace(tzinfo=timezone.utc)

        if campaign_start and campaign_start > current_time:
            print(f"[CAMPAIGN START] Campaign scheduled for {campaign.start_date}, not processing queue now")
            return {
                "success": success,
                "status": "scheduled",
                "scheduled_for": campaign.start_date.isoformat(),
                "message": f"Campaign scheduled to start at {campaign.start_date.isoformat()}"
            }

        # Process campaign queue immediately (async)
        try:
            await campaign_execution_service.process_campaign_queue(
                db,
                campaign_id,
                current_user.company_id
            )
        except Exception as e:
            print(f"[CAMPAIGN START] Error processing queue: {e}")
            import traceback
            traceback.print_exc()

    return {"success": success, "status": "active"}


@router.post("/{campaign_id}/pause")
def pause_campaign(
    campaign_id: int,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Pause a campaign
    """
    campaign = campaign_execution_service.pause_campaign(
        db=db,
        campaign_id=campaign_id,
        company_id=current_user.company_id
    )

    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    return {"success": True, "status": campaign.status.value}


@router.post("/{campaign_id}/resume")
def resume_campaign(
    campaign_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Resume a paused campaign
    """
    campaign = campaign_execution_service.resume_campaign(
        db=db,
        campaign_id=campaign_id,
        company_id=current_user.company_id
    )

    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    # Queue pending messages
    background_tasks.add_task(
        campaign_execution_service.process_campaign_queue,
        db,
        campaign_id,
        current_user.company_id
    )

    return {"success": True, "status": campaign.status.value}


@router.post("/{campaign_id}/relaunch")
async def relaunch_campaign(
    campaign_id: int,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Re-launch a completed campaign - resets enrollments and starts fresh
    """
    from datetime import timezone
    from app.models.campaign_contact import CampaignContact as CampaignContactModel
    from app.models.campaign_contact import EnrollmentStatus

    campaign = campaign_service.get_campaign(db=db, campaign_id=campaign_id, company_id=current_user.company_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    if campaign.status != CampaignStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="Only completed campaigns can be re-launched")

    print(f"[RELAUNCH] Re-launching campaign {campaign_id}: {campaign.name}")

    # Reset all enrollments to pending status
    db.query(CampaignContactModel).filter(
        CampaignContactModel.campaign_id == campaign_id
    ).update({
        'status': EnrollmentStatus.PENDING,
        'current_step': 0,
        'current_message_id': None,
        'next_scheduled_at': None,
        'completed_at': None,
        'last_interaction_at': None
    })

    # Reset campaign status to draft
    campaign.status = CampaignStatus.DRAFT
    campaign.end_date = None
    # Keep start_date if user wants to schedule, or they can update it

    db.commit()
    db.refresh(campaign)

    print(f"[RELAUNCH] Campaign {campaign_id} reset to draft with enrollments pending")

    return {
        "success": True,
        "status": "draft",
        "message": "Campaign has been reset and is ready to re-launch"
    }


# Campaign Analytics


@router.get("/{campaign_id}/analytics/performance")
def get_campaign_performance(
    campaign_id: int,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Get performance metrics for a campaign
    """
    metrics = campaign_analytics_service.get_campaign_performance_metrics(
        db=db,
        campaign_id=campaign_id,
        company_id=current_user.company_id
    )

    if not metrics:
        raise HTTPException(status_code=404, detail="Campaign not found")

    return metrics


@router.get("/{campaign_id}/analytics/funnel")
def get_campaign_funnel(
    campaign_id: int,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Get campaign funnel showing drop-off at each stage
    """
    funnel = campaign_analytics_service.get_campaign_funnel(
        db=db,
        campaign_id=campaign_id,
        company_id=current_user.company_id
    )

    return {"campaign_id": campaign_id, "funnel": funnel}


@router.get("/{campaign_id}/analytics/messages")
def get_message_performance(
    campaign_id: int,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Get performance metrics for each message in the campaign
    """
    performance = campaign_analytics_service.get_message_performance(
        db=db,
        campaign_id=campaign_id,
        company_id=current_user.company_id
    )

    return {"campaign_id": campaign_id, "messages": performance}


@router.get("/{campaign_id}/analytics/time-series")
def get_time_series_metrics(
    campaign_id: int,
    metric: str = "conversions",
    interval: str = "day",
    days: int = 30,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Get time-series data for a specific metric
    """
    data = campaign_analytics_service.get_time_series_metrics(
        db=db,
        campaign_id=campaign_id,
        company_id=current_user.company_id,
        metric=metric,
        interval=interval,
        days=days
    )

    return {
        "campaign_id": campaign_id,
        "metric": metric,
        "interval": interval,
        "data": data
    }


# CRM Analytics


@router.get("/analytics/pipeline")
def get_pipeline_metrics(
    date_range_days: Optional[int] = 30,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Get lead pipeline metrics across all campaigns
    """
    return campaign_analytics_service.get_lead_pipeline_metrics(
        db=db,
        company_id=current_user.company_id,
        date_range_days=date_range_days
    )


@router.post("/analytics/compare")
def compare_campaigns(
    campaign_ids: List[int],
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Compare performance across multiple campaigns
    """
    comparison = campaign_analytics_service.get_campaign_comparison(
        db=db,
        company_id=current_user.company_id,
        campaign_ids=campaign_ids
    )

    return {"campaigns": comparison}


@router.get("/by-type/{campaign_type}", response_model=List[schemas_campaign.Campaign])
def get_campaigns_by_type(
    campaign_type: str,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Get campaigns by type (email, sms, whatsapp, voice, multi_channel)
    """
    from app.models.campaign import Campaign, CampaignType

    campaigns = db.query(Campaign).filter(
        Campaign.company_id == current_user.company_id,
        Campaign.campaign_type == CampaignType(campaign_type)
    ).order_by(Campaign.created_at.desc()).offset(skip).limit(limit).all()

    return campaigns


@router.post("/{campaign_id}/clone", response_model=schemas_campaign.Campaign)
def clone_campaign(
    campaign_id: int,
    new_name: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Clone an existing campaign with all its settings and messages
    """
    from app.models.campaign import Campaign, CampaignStatus
    from app.models.campaign_message import CampaignMessage
    import json

    # Get original campaign
    original = db.query(Campaign).filter(
        Campaign.id == campaign_id,
        Campaign.company_id == current_user.company_id
    ).first()

    if not original:
        raise HTTPException(status_code=404, detail="Campaign not found")

    # Create clone
    clone_data = {
        "name": new_name or f"{original.name} (Copy)",
        "description": original.description,
        "campaign_type": original.campaign_type,
        "status": CampaignStatus.DRAFT,
        "target_criteria": original.target_criteria,
        "goal_type": original.goal_type,
        "goal_value": original.goal_value,
        "budget": original.budget,
        "settings": original.settings,
        "twilio_config": original.twilio_config,
        "workflow_id": original.workflow_id,
        "agent_id": original.agent_id,
        "company_id": current_user.company_id,
        "created_by_user_id": current_user.id,
        "owner_user_id": current_user.id
    }

    cloned_campaign = Campaign(**clone_data)
    db.add(cloned_campaign)
    db.commit()
    db.refresh(cloned_campaign)

    # Clone messages
    original_messages = db.query(CampaignMessage).filter(
        CampaignMessage.campaign_id == campaign_id
    ).all()

    for msg in original_messages:
        cloned_msg = CampaignMessage(
            campaign_id=cloned_campaign.id,
            step_number=msg.step_number,
            message_type=msg.message_type,
            subject=msg.subject,
            content=msg.content,
            voice_script=msg.voice_script,
            tts_voice_id=msg.tts_voice_id,
            voice_agent_id=msg.voice_agent_id,
            call_flow_config=msg.call_flow_config,
            delay_amount=msg.delay_amount,
            delay_unit=msg.delay_unit,
            send_time=msg.send_time,
            from_email=msg.from_email,
            from_name=msg.from_name,
            twilio_phone_number=msg.twilio_phone_number,
            personalization_tokens=msg.personalization_tokens,
            ab_test_variant=msg.ab_test_variant
        )
        db.add(cloned_msg)

    db.commit()

    return cloned_campaign


@router.get("/{campaign_id}/summary")
def get_campaign_summary(
    campaign_id: int,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Get a quick summary of campaign status and key metrics
    """
    from app.models.campaign import Campaign
    from app.models.campaign_contact import CampaignContact

    campaign = db.query(Campaign).filter(
        Campaign.id == campaign_id,
        Campaign.company_id == current_user.company_id
    ).first()

    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    # Get enrollment stats
    total_enrolled = db.query(CampaignContact).filter(
        CampaignContact.campaign_id == campaign_id
    ).count()

    from app.models.campaign_contact import EnrollmentStatus
    active_count = db.query(CampaignContact).filter(
        CampaignContact.campaign_id == campaign_id,
        CampaignContact.status == EnrollmentStatus.ACTIVE
    ).count()

    completed_count = db.query(CampaignContact).filter(
        CampaignContact.campaign_id == campaign_id,
        CampaignContact.status == EnrollmentStatus.COMPLETED
    ).count()

    return {
        "campaign_id": campaign.id,
        "name": campaign.name,
        "type": campaign.campaign_type.value,
        "status": campaign.status.value,
        "total_enrolled": total_enrolled,
        "active": active_count,
        "completed": completed_count,
        "completion_rate": (completed_count / total_enrolled * 100) if total_enrolled > 0 else 0,
        "total_contacts_reached": campaign.contacts_reached,
        "total_contacts_engaged": campaign.contacts_engaged,
        "engagement_rate": (campaign.contacts_engaged / campaign.contacts_reached * 100) if campaign.contacts_reached > 0 else 0,
        "total_revenue": float(campaign.total_revenue) if campaign.total_revenue else 0,
        "actual_cost": float(campaign.actual_cost) if campaign.actual_cost else 0,
        "roi": ((float(campaign.total_revenue) - float(campaign.actual_cost)) / float(campaign.actual_cost) * 100) if campaign.actual_cost and campaign.actual_cost > 0 else 0
    }


@router.post("/{campaign_id}/test-send")
def test_campaign_send(
    campaign_id: int,
    test_contact_id: int,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Send a test message to a single contact to preview campaign
    """
    from app.models.campaign import Campaign
    from app.models.contact import Contact
    from app.models.campaign_message import CampaignMessage

    campaign = db.query(Campaign).filter(
        Campaign.id == campaign_id,
        Campaign.company_id == current_user.company_id
    ).first()

    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    contact = db.query(Contact).filter(
        Contact.id == test_contact_id,
        Contact.company_id == current_user.company_id
    ).first()

    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")

    # Get first message
    first_message = db.query(CampaignMessage).filter(
        CampaignMessage.campaign_id == campaign_id
    ).order_by(CampaignMessage.step_number).first()

    if not first_message:
        raise HTTPException(status_code=400, detail="Campaign has no messages")

    # Here you would integrate with actual sending service
    # For now, just return a preview

    from app.services import campaign_execution_service
    from app.models.lead import Lead

    lead = db.query(Lead).filter(Lead.contact_id == test_contact_id).first()

    personalized_content = campaign_execution_service.personalize_message(
        first_message.content,
        contact,
        lead
    )

    personalized_subject = campaign_execution_service.personalize_message(
        first_message.subject or "",
        contact,
        lead
    ) if first_message.subject else None

    return {
        "message": "Test preview generated",
        "contact": {
            "id": contact.id,
            "name": contact.name,
            "email": contact.email
        },
        "message_type": first_message.message_type.value,
        "subject": personalized_subject,
        "content": personalized_content,
        "note": "This is a preview only. Actual sending not implemented in test mode."
    }
