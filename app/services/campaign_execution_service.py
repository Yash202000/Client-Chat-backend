"""
Campaign Execution Service
Orchestrates the sending of campaign messages across multiple channels
"""
from sqlalchemy.orm import Session
from sqlalchemy import or_
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from app.models.campaign import Campaign, CampaignStatus
from app.models.campaign_contact import CampaignContact, EnrollmentStatus
from app.models.campaign_message import CampaignMessage, MessageType, DelayUnit
from app.models.campaign_activity import CampaignActivity, ActivityType
from app.models.contact import Contact
from app.models.lead import Lead
from app.models.integration import Integration
from app.services import campaign_service, integration_service
from app.services import messaging_service, email_service
import asyncio
import logging
logger = logging.getLogger(__name__)


def calculate_next_send_time(
    enrollment: CampaignContact,
    message: CampaignMessage,
    current_time: datetime = None
) -> datetime:
    """
    Calculate when the next message should be sent based on delay configuration
    """
    if current_time is None:
        current_time = datetime.utcnow()

    # Calculate delay
    delay_amount = message.delay_amount or 0
    delay_unit = message.delay_unit or DelayUnit.DAYS

    if delay_unit == DelayUnit.MINUTES:
        next_time = current_time + timedelta(minutes=delay_amount)
    elif delay_unit == DelayUnit.HOURS:
        next_time = current_time + timedelta(hours=delay_amount)
    elif delay_unit == DelayUnit.DAYS:
        next_time = current_time + timedelta(days=delay_amount)
    elif delay_unit == DelayUnit.WEEKS:
        next_time = current_time + timedelta(weeks=delay_amount)
    else:
        next_time = current_time

    # Apply send time window if configured
    if message.send_time_window_start and message.send_time_window_end:
        try:
            start_hour, start_min = map(int, message.send_time_window_start.split(':'))
            end_hour, end_min = map(int, message.send_time_window_end.split(':'))

            # If next_time falls outside the window, adjust it
            if next_time.hour < start_hour or (next_time.hour == start_hour and next_time.minute < start_min):
                next_time = next_time.replace(hour=start_hour, minute=start_min)
            elif next_time.hour > end_hour or (next_time.hour == end_hour and next_time.minute > end_min):
                # Move to next day within window
                next_time = next_time + timedelta(days=1)
                next_time = next_time.replace(hour=start_hour, minute=start_min)
        except:
            logger.exception("Unexpected error")

    # Skip weekends if configured
    if message.send_on_weekdays_only:
        while next_time.weekday() >= 5:  # Saturday = 5, Sunday = 6
            next_time = next_time + timedelta(days=1)

    return next_time


def personalize_message(content: str, contact: Contact, lead: Optional[Lead] = None) -> str:
    """
    Replace personalization tokens in message content
    """
    if not content:
        return content

    # Contact personalization
    replacements = {
        '{{first_name}}': contact.name.split()[0] if contact.name and ' ' in contact.name else contact.name or '',
        '{{name}}': contact.name or '',
        '{{email}}': contact.email or '',
        '{{phone}}': contact.phone_number or '',
        '{{phone_number}}': contact.phone_number or '',
    }

    # Lead personalization
    if lead:
        replacements.update({
            '{{deal_value}}': str(lead.deal_value) if lead.deal_value else '',
            '{{lead_stage}}': lead.stage.value if lead.stage else '',
            '{{lead_score}}': str(lead.score) if lead.score else '',
        })

    # Apply replacements
    personalized = content
    for token, value in replacements.items():
        personalized = personalized.replace(token, value)

    return personalized


async def send_email_message(
    db: Session,
    campaign: Campaign,
    message: CampaignMessage,
    contact: Contact,
    enrollment: CampaignContact
) -> bool:
    """
    Send an email campaign message using SMTP
    """
    try:
        from app.models.company_settings import CompanySettings

        # Validate contact has email
        if not contact.email:
            return False

        # Personalize content
        subject = personalize_message(message.subject or "Campaign Message", contact, enrollment.lead)

        # Personalize both HTML and text content
        html_content = None
        text_content = None

        if message.html_body:
            html_content = personalize_message(message.html_body, contact, enrollment.lead)

        if message.body:
            text_content = personalize_message(message.body, contact, enrollment.lead)

        # If neither is set, use body as text
        if not html_content and not text_content:
            text_content = personalize_message(message.body or "Campaign message", contact, enrollment.lead)

        # Get SMTP config from company settings (required)
        smtp_config = None
        from_email = None
        from_name = None

        # First check campaign-specific settings
        if campaign.settings and 'smtp_config' in campaign.settings:
            smtp_config = campaign.settings['smtp_config']
            from_email = campaign.settings.get('from_email')
            from_name = campaign.settings.get('from_name')

        # Fall back to company settings
        if not smtp_config:
            company_settings = db.query(CompanySettings).filter(
                CompanySettings.company_id == campaign.company_id
            ).first()

            if company_settings and company_settings.smtp_host:
                smtp_config = {
                    'host': company_settings.smtp_host,
                    'port': company_settings.smtp_port or 587,
                    'user': company_settings.smtp_user,
                    'password': company_settings.smtp_password,
                    'use_tls': company_settings.smtp_use_tls if company_settings.smtp_use_tls is not None else True,
                }
                from_email = from_email or company_settings.smtp_from_email
                from_name = from_name or company_settings.smtp_from_name

        # SMTP config is required - no global fallback
        if not smtp_config:
            return False


        # Send via email service
        result = await email_service.send_email_smtp(
            to_email=contact.email,
            subject=subject,
            html_content=html_content,
            text_content=text_content,
            from_email=from_email,
            from_name=from_name,
            smtp_config=smtp_config
        )


        # Record activity
        activity = CampaignActivity(
            campaign_id=campaign.id,
            contact_id=contact.id,
            lead_id=enrollment.lead_id,
            message_id=message.id,
            activity_type=ActivityType.EMAIL_SENT,
            activity_data={
                'subject': subject,
                'to': contact.email,
                'message_id': result.get('message_id'),
                'status': result.get('status')
            }
        )
        db.add(activity)

        return True

    except Exception as e:
        # Record error activity
        activity = CampaignActivity(
            campaign_id=campaign.id,
            contact_id=contact.id,
            lead_id=enrollment.lead_id,
            message_id=message.id,
            activity_type=ActivityType.ERROR,
            error_message=str(e)
        )
        db.add(activity)
        return False


async def send_sms_message(
    db: Session,
    campaign: Campaign,
    message: CampaignMessage,
    contact: Contact,
    enrollment: CampaignContact
) -> bool:
    """
    Send an SMS campaign message via Twilio
    """
    try:
        from twilio.rest import Client
        from app.core.config import settings

        # Validate contact has phone number
        if not contact.phone_number:
            return False

        # Get Twilio credentials from campaign config or settings
        twilio_config = campaign.twilio_config or {}
        account_sid = twilio_config.get('account_sid') or settings.TWILIO_ACCOUNT_SID
        auth_token = twilio_config.get('auth_token') or settings.TWILIO_AUTH_TOKEN
        from_number = twilio_config.get('phone_number') or settings.TWILIO_PHONE_NUMBER

        # Validate Twilio configuration
        if not all([account_sid, auth_token, from_number]):
            raise ValueError("Twilio credentials are not configured. Please set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, and TWILIO_PHONE_NUMBER in settings or campaign config.")

        # Personalize message content
        body = personalize_message(message.body, contact, enrollment.lead)


        # Send via Twilio
        client = Client(account_sid, auth_token)
        twilio_message = client.messages.create(
            body=body,
            from_=from_number,
            to=contact.phone_number
        )


        # Record activity
        activity = CampaignActivity(
            campaign_id=campaign.id,
            contact_id=contact.id,
            lead_id=enrollment.lead_id,
            message_id=message.id,
            activity_type=ActivityType.SMS_SENT,
            activity_data={
                'to': contact.phone_number,
                'from': from_number,
                'body': body,
                'twilio_sid': twilio_message.sid,
                'status': twilio_message.status
            }
        )
        db.add(activity)

        return True

    except Exception as e:
        # Record error activity
        activity = CampaignActivity(
            campaign_id=campaign.id,
            contact_id=contact.id,
            lead_id=enrollment.lead_id,
            message_id=message.id,
            activity_type=ActivityType.ERROR,
            error_message=str(e)
        )
        db.add(activity)
        return False


async def send_whatsapp_message(
    db: Session,
    campaign: Campaign,
    message: CampaignMessage,
    contact: Contact,
    enrollment: CampaignContact
) -> bool:
    """
    Send a WhatsApp campaign message using Meta Cloud API
    """
    try:
        # Get WhatsApp integration for the company
        integration = db.query(Integration).filter(
            Integration.company_id == campaign.company_id,
            Integration.type == "whatsapp",
            Integration.is_active == True
        ).first()

        if not integration:
            return False

        # Personalize content
        body = personalize_message(message.body, contact, enrollment.lead)

        # Send via existing messaging service
        result = await messaging_service.send_whatsapp_message(
            recipient_phone_number=contact.phone_number,
            message_text=body,
            integration=integration
        )


        # Record activity
        activity = CampaignActivity(
            campaign_id=campaign.id,
            contact_id=contact.id,
            lead_id=enrollment.lead_id,
            message_id=message.id,
            activity_type=ActivityType.WHATSAPP_SENT,
            activity_data={
                'to': contact.phone_number,
                'body': body,
                'whatsapp_message_id': result.get('messages', [{}])[0].get('id')
            }
        )
        db.add(activity)

        return True

    except Exception as e:
        # Record error activity
        activity = CampaignActivity(
            campaign_id=campaign.id,
            contact_id=contact.id,
            lead_id=enrollment.lead_id,
            message_id=message.id,
            activity_type=ActivityType.ERROR,
            error_message=str(e)
        )
        db.add(activity)
        return False


async def send_instagram_message(
    db: Session,
    campaign: Campaign,
    message: CampaignMessage,
    contact: Contact,
    enrollment: CampaignContact
) -> bool:
    """
    Send an Instagram campaign message using Meta Graph API
    """
    try:
        # Get Instagram integration for the company
        integration = db.query(Integration).filter(
            Integration.company_id == campaign.company_id,
            Integration.type == "instagram",
            Integration.is_active == True
        ).first()

        if not integration:
            return False

        # Check if contact has Instagram ID
        if not contact.instagram_id:
            return False

        # Personalize content
        body = personalize_message(message.body, contact, enrollment.lead)

        # Send via existing messaging service
        result = await messaging_service.send_instagram_message(
            recipient_psid=contact.instagram_id,
            message_text=body,
            integration=integration
        )


        # Record activity
        activity = CampaignActivity(
            campaign_id=campaign.id,
            contact_id=contact.id,
            lead_id=enrollment.lead_id,
            message_id=message.id,
            activity_type=ActivityType.MESSAGE_SENT,
            activity_data={
                'platform': 'instagram',
                'to': contact.instagram_id,
                'body': body,
                'message_id': result.get('message_id')
            }
        )
        db.add(activity)

        return True

    except Exception as e:
        # Record error activity
        activity = CampaignActivity(
            campaign_id=campaign.id,
            contact_id=contact.id,
            lead_id=enrollment.lead_id,
            message_id=message.id,
            activity_type=ActivityType.ERROR,
            error_message=str(e)
        )
        db.add(activity)
        return False


async def send_telegram_message(
    db: Session,
    campaign: Campaign,
    message: CampaignMessage,
    contact: Contact,
    enrollment: CampaignContact
) -> bool:
    """
    Send a Telegram campaign message using Telegram Bot API
    """
    try:
        # Get Telegram integration for the company
        integration = db.query(Integration).filter(
            Integration.company_id == campaign.company_id,
            Integration.type == "telegram",
            Integration.is_active == True
        ).first()

        if not integration:
            return False

        # Check if contact has Telegram chat ID
        if not contact.telegram_chat_id:
            return False

        # Personalize content
        body = personalize_message(message.body, contact, enrollment.lead)

        # Send via existing messaging service
        result = await messaging_service.send_telegram_message(
            chat_id=contact.telegram_chat_id,
            message_text=body,
            integration=integration
        )


        # Record activity
        activity = CampaignActivity(
            campaign_id=campaign.id,
            contact_id=contact.id,
            lead_id=enrollment.lead_id,
            message_id=message.id,
            activity_type=ActivityType.MESSAGE_SENT,
            activity_data={
                'platform': 'telegram',
                'to': contact.telegram_chat_id,
                'body': body,
                'message_id': result.get('result', {}).get('message_id')
            }
        )
        db.add(activity)

        return True

    except Exception as e:
        # Record error activity
        activity = CampaignActivity(
            campaign_id=campaign.id,
            contact_id=contact.id,
            lead_id=enrollment.lead_id,
            message_id=message.id,
            activity_type=ActivityType.ERROR,
            error_message=str(e)
        )
        db.add(activity)
        return False


async def initiate_voice_call(
    db: Session,
    campaign: Campaign,
    message: CampaignMessage,
    contact: Contact,
    enrollment: CampaignContact
) -> bool:
    """Initiate a voice call campaign message via Twilio."""
    try:
        from app.services import voice_campaign_service
        result = await voice_campaign_service.initiate_outbound_campaign_call(
            db=db,
            campaign=campaign,
            message=message,
            contact=contact,
            enrollment=enrollment
        )
        if result.get('success'):
            enrollment.calls_initiated += 1
            db.commit()
        return result.get('success', False)

    except Exception as e:
        activity = CampaignActivity(
            campaign_id=campaign.id,
            contact_id=contact.id,
            lead_id=enrollment.lead_id,
            message_id=message.id,
            activity_type=ActivityType.CALL_FAILED,
            error_message=str(e)
        )
        db.add(activity)
        db.commit()
        return False


async def send_linkedin_dm_message(
    db: Session,
    campaign: Campaign,
    message: CampaignMessage,
    contact: Contact,
    enrollment: CampaignContact
) -> bool:
    """Send a LinkedIn DM to a contact via their stored LinkedIn URN."""
    try:
        linkedin_urn = contact.linkedin_urn if hasattr(contact, 'linkedin_urn') else None
        if not linkedin_urn:
            return False

        integration = integration_service.get_integration_by_type_and_company(db, "linkedin", campaign.company_id)
        if not integration:
            raise Exception("LinkedIn integration not configured")

        body = message.body or ""
        if contact.first_name:
            body = body.replace("{first_name}", contact.first_name)
        if contact.email:
            body = body.replace("{email}", contact.email)

        await messaging_service.send_linkedin_message(
            recipient_urn=linkedin_urn,
            message_text=body,
            integration=integration,
        )

        activity = CampaignActivity(
            campaign_id=campaign.id,
            contact_id=contact.id,
            lead_id=enrollment.lead_id,
            message_id=message.id,
            activity_type=ActivityType.MESSAGE_SENT,
            activity_data={"channel": "linkedin_dm", "recipient_urn": linkedin_urn},
        )
        db.add(activity)
        db.commit()
        return True

    except Exception as e:
        activity = CampaignActivity(
            campaign_id=campaign.id,
            contact_id=contact.id,
            lead_id=enrollment.lead_id,
            message_id=message.id,
            activity_type=ActivityType.ERROR,
            error_message=str(e),
        )
        db.add(activity)
        db.commit()
        return False


async def send_campaign_message(
    db: Session,
    campaign_id: int,
    enrollment_id: int,
    company_id: int
) -> bool:
    """
    Send the next message in the campaign sequence for a specific enrollment
    """
    # Get enrollment with related data
    enrollment = db.query(CampaignContact).filter(
        CampaignContact.id == enrollment_id
    ).first()

    if not enrollment or enrollment.status != EnrollmentStatus.ACTIVE:
        return False

    # Get campaign
    campaign = campaign_service.get_campaign(db, campaign_id, company_id)
    if not campaign or campaign.status != CampaignStatus.ACTIVE:
        return False

    # Get next message in sequence
    next_message = db.query(CampaignMessage).filter(
        CampaignMessage.campaign_id == campaign_id,
        CampaignMessage.sequence_order == enrollment.current_step + 1,
        CampaignMessage.is_active == True
    ).first()

    if not next_message:
        # No more messages, mark as completed
        enrollment.status = EnrollmentStatus.COMPLETED
        enrollment.completed_at = datetime.utcnow()
        db.commit()
        return True

    # Check send conditions if any
    if next_message.send_conditions:
        # Implement condition checking logic here
        pass

    # Get contact
    contact = db.query(Contact).filter(Contact.id == enrollment.contact_id).first()
    if not contact or contact.do_not_contact:
        enrollment.status = EnrollmentStatus.FAILED
        db.commit()
        return False

    # Get lead if exists
    lead = None
    if enrollment.lead_id:
        lead = db.query(Lead).filter(Lead.id == enrollment.lead_id).first()

    # Send message based on type
    # Handle both Enum and string comparisons
    msg_type = next_message.message_type
    if isinstance(msg_type, str):
        msg_type = msg_type.lower()
    else:
        msg_type = msg_type.value if hasattr(msg_type, 'value') else str(msg_type).lower()


    success = False
    if msg_type == "email":
        success = await send_email_message(db, campaign, next_message, contact, enrollment)
    elif msg_type == "sms":
        success = await send_sms_message(db, campaign, next_message, contact, enrollment)
    elif msg_type == "whatsapp":
        success = await send_whatsapp_message(db, campaign, next_message, contact, enrollment)
    elif msg_type == "instagram":
        success = await send_instagram_message(db, campaign, next_message, contact, enrollment)
    elif msg_type == "telegram":
        success = await send_telegram_message(db, campaign, next_message, contact, enrollment)
    elif msg_type == "voice":
        success = await initiate_voice_call(db, campaign, next_message, contact, enrollment)
    elif msg_type == "linkedin_dm":
        success = await send_linkedin_dm_message(db, campaign, next_message, contact, enrollment)
    else:
        pass

    if success:
        # Update enrollment progress
        enrollment.current_step += 1
        enrollment.current_message_id = next_message.id
        enrollment.last_interaction_at = datetime.utcnow()

        # Calculate next send time
        next_send_time = calculate_next_send_time(enrollment, next_message)
        enrollment.next_scheduled_at = next_send_time

        db.commit()

    return success


async def process_campaign_queue(db: Session, campaign_id: int, company_id: int):
    """
    Process all pending campaign messages that are due to be sent
    """
    import traceback

    current_time = datetime.utcnow()

    # Get all active enrollments with messages due
    due_enrollments = db.query(CampaignContact).join(Campaign).filter(
        CampaignContact.campaign_id == campaign_id,
        CampaignContact.status == EnrollmentStatus.ACTIVE,
        Campaign.company_id == company_id,
        Campaign.status == CampaignStatus.ACTIVE,
        or_(
            CampaignContact.next_scheduled_at <= current_time,
            CampaignContact.next_scheduled_at == None
        )
    ).all()


    if len(due_enrollments) == 0:
        # Debug: check why no enrollments
        all_enrollments = db.query(CampaignContact).filter(
            CampaignContact.campaign_id == campaign_id
        ).all()
        for e in all_enrollments:
            pass

    # Send messages concurrently
    async def _send_one(enrollment):
        try:
            return await send_campaign_message(db, campaign_id, enrollment.id, company_id)
        except Exception as e:
            traceback.print_exc()
            return None

    await asyncio.gather(*[_send_one(e) for e in due_enrollments])

    # Update campaign metrics
    try:
        campaign_service.update_campaign_metrics(db, campaign_id, company_id)
    except Exception as e:
        logger.exception(e)


def start_campaign(db: Session, campaign_id: int, company_id: int):
    """
    Start a campaign - activate all pending enrollments and schedule first messages

    If the campaign has a start_date in the future, messages will be scheduled for that time.
    If start_date is not set or is in the past, messages will be scheduled starting from now.
    """
    campaign = campaign_service.get_campaign(db, campaign_id, company_id)
    if not campaign:
        return False


    # Update campaign status
    campaign.status = CampaignStatus.ACTIVE

    # Determine the effective start time
    # Use timezone-aware UTC time for consistent comparison
    from datetime import timezone
    current_time = datetime.now(timezone.utc)

    # Normalize campaign.start_date to be timezone-aware for comparison
    campaign_start = campaign.start_date
    if campaign_start:
        # If naive datetime, assume it's UTC
        if campaign_start.tzinfo is None:
            campaign_start = campaign_start.replace(tzinfo=timezone.utc)


    # Use the user's start_date if it's set and in the future, otherwise use current time
    if campaign_start and campaign_start > current_time:
        effective_start_time = campaign.start_date  # Keep original for storage
    else:
        # Only set start_date if it wasn't set by user
        if not campaign.start_date:
            campaign.start_date = current_time.replace(tzinfo=None)  # Store as naive UTC
        effective_start_time = current_time.replace(tzinfo=None)

    # Get all enrollments that need to be activated (PENDING or COMPLETED for re-launch)
    enrollments_to_activate = db.query(CampaignContact).filter(
        CampaignContact.campaign_id == campaign_id,
        CampaignContact.status.in_([EnrollmentStatus.PENDING, EnrollmentStatus.COMPLETED])
    ).all()


    # Get first message
    first_message = db.query(CampaignMessage).filter(
        CampaignMessage.campaign_id == campaign_id,
        CampaignMessage.sequence_order == 1,
        CampaignMessage.is_active == True
    ).first()

    if first_message:
        for enrollment in enrollments_to_activate:
            # Reset enrollment for fresh start
            enrollment.status = EnrollmentStatus.ACTIVE
            enrollment.current_step = 0
            enrollment.current_message_id = None
            enrollment.completed_at = None
            # Schedule based on the effective start time (user's start_date or now)
            enrollment.next_scheduled_at = calculate_next_send_time(enrollment, first_message, effective_start_time)
    else:
        # Check all messages for this campaign
        all_messages = db.query(CampaignMessage).filter(
            CampaignMessage.campaign_id == campaign_id
        ).all()
        for msg in all_messages:
            pass

    campaign.last_run_at = datetime.utcnow()
    db.commit()

    return True


def pause_campaign(db: Session, campaign_id: int, company_id: int):
    """
    Pause a campaign - set all active enrollments to paused
    """
    campaign = campaign_service.update_campaign_status(db, campaign_id, CampaignStatus.PAUSED, company_id)

    # Pause all active enrollments
    db.query(CampaignContact).filter(
        CampaignContact.campaign_id == campaign_id,
        CampaignContact.status == EnrollmentStatus.ACTIVE
    ).update({'status': EnrollmentStatus.PAUSED})

    db.commit()
    return campaign


def resume_campaign(db: Session, campaign_id: int, company_id: int):
    """
    Resume a paused campaign
    """
    campaign = campaign_service.update_campaign_status(db, campaign_id, CampaignStatus.ACTIVE, company_id)

    # Resume all paused enrollments
    db.query(CampaignContact).filter(
        CampaignContact.campaign_id == campaign_id,
        CampaignContact.status == EnrollmentStatus.PAUSED
    ).update({'status': EnrollmentStatus.ACTIVE})

    db.commit()
    return campaign


async def process_all_scheduled_campaigns(db: Session):
    """
    Background job to process all active campaigns with due messages.
    This should be called periodically by a scheduler.
    """
    from datetime import timezone
    import traceback

    current_time = datetime.now(timezone.utc)

    try:
        # Find all active campaigns
        active_campaigns = db.query(Campaign).filter(
            Campaign.status == CampaignStatus.ACTIVE
        ).all()

        if not active_campaigns:
            return


        # Single query to find which campaigns have due enrollments (avoids N count queries)
        active_ids = [c.id for c in active_campaigns]
        due_campaign_ids = {
            row[0]
            for row in db.query(CampaignContact.campaign_id).filter(
                CampaignContact.campaign_id.in_(active_ids),
                CampaignContact.status == EnrollmentStatus.ACTIVE,
                or_(
                    CampaignContact.next_scheduled_at <= current_time.replace(tzinfo=None),
                    CampaignContact.next_scheduled_at == None,
                ),
            ).distinct().all()
        }

        for campaign in active_campaigns:
            if campaign.id not in due_campaign_ids:
                continue
            try:
                await process_campaign_queue(db, campaign.id, campaign.company_id)
            except Exception as e:
                traceback.print_exc()

    except Exception as e:
        traceback.print_exc()
