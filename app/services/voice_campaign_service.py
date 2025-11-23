"""
Voice Campaign Service
Handles Twilio voice call campaigns with AI agent integration
"""
from sqlalchemy.orm import Session
from typing import Optional, Dict, Any
from datetime import datetime
from app.models.campaign import Campaign
from app.models.campaign_message import CampaignMessage
from app.models.campaign_contact import CampaignContact
from app.models.campaign_activity import CampaignActivity, ActivityType
from app.models.contact import Contact
from app.models.agent import Agent


async def initiate_outbound_campaign_call(
    db: Session,
    campaign: Campaign,
    message: CampaignMessage,
    contact: Contact,
    enrollment: CampaignContact
) -> Dict[str, Any]:
    """
    Initiate an outbound voice call for a campaign using Twilio
    """
    try:
        from twilio.rest import Client
        from app.services.integration_service import get_integration_by_type

        # Get Twilio credentials
        twilio_integration = get_integration_by_type(db, campaign.company_id, "twilio")
        if not twilio_integration:
            raise Exception("Twilio integration not configured")

        twilio_config = twilio_integration.config or {}
        account_sid = twilio_config.get('account_sid')
        auth_token = twilio_config.get('auth_token')

        if not account_sid or not auth_token:
            raise Exception("Twilio credentials not found")

        client = Client(account_sid, auth_token)

        # Get call configuration
        call_config = message.call_flow_config or {}
        from_number = message.twilio_phone_number or campaign.twilio_config.get('from_number')

        if not from_number:
            raise Exception("No Twilio phone number configured")

        # Determine call type: AI agent or TTS script
        if message.voice_agent_id:
            # AI agent-powered call
            twiml_url = f"{get_base_url()}/api/v1/voice-campaigns/{campaign.id}/twiml/{enrollment.id}"
        else:
            # Simple TTS script
            twiml_url = f"{get_base_url()}/api/v1/voice-campaigns/{campaign.id}/tts/{enrollment.id}"

        # Create call
        call = client.calls.create(
            to=contact.phone_number,
            from_=from_number,
            url=twiml_url,
            status_callback=f"{get_base_url()}/api/v1/voice-campaigns/{campaign.id}/callback",
            status_callback_event=['initiated', 'ringing', 'answered', 'completed'],
            status_callback_method='POST',
            record=call_config.get('record_call', False),
            recording_status_callback=f"{get_base_url()}/api/v1/voice-campaigns/{campaign.id}/recording-callback" if call_config.get('record_call') else None,
            machine_detection=('DetectMessageEnd' if call_config.get('voicemail_detection') else None),
            timeout=call_config.get('ring_timeout', 30)
        )

        # Record activity
        activity = CampaignActivity(
            campaign_id=campaign.id,
            contact_id=contact.id,
            lead_id=enrollment.lead_id,
            message_id=message.id,
            activity_type=ActivityType.CALL_INITIATED,
            external_id=call.sid,
            activity_data={
                'call_sid': call.sid,
                'to': contact.phone_number,
                'from': from_number,
                'status': call.status
            }
        )
        db.add(activity)
        db.commit()

        return {
            'success': True,
            'call_sid': call.sid,
            'status': call.status
        }

    except Exception as e:
        print(f"[VOICE CAMPAIGN] Call initiation failed: {e}")

        # Record error
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

        return {
            'success': False,
            'error': str(e)
        }


def generate_twiml_for_ai_agent(
    db: Session,
    campaign: Campaign,
    message: CampaignMessage,
    contact: Contact,
    enrollment: CampaignContact
) -> str:
    """
    Generate TwiML that connects to an AI agent via LiveKit or similar
    """
    from twilio.twiml.voice_response import VoiceResponse, Connect

    response = VoiceResponse()

    # Get AI agent
    agent = db.query(Agent).filter(Agent.id == message.voice_agent_id).first()
    if not agent:
        response.say("We're sorry, but we're experiencing technical difficulties. Please try again later.")
        return str(response)

    # Personalize greeting
    greeting = message.voice_script or f"Hello {contact.name or 'there'}, this is {agent.name}."

    # Say greeting
    response.say(greeting, voice=message.tts_voice_id or 'alice')

    # Connect to AI agent via WebSocket (LiveKit integration)
    # This would connect to your LiveKit voice agent
    connect = Connect()
    connect.stream(
        url=f"wss://{get_base_url()}/api/v1/voice-agent-stream",
        name=f"campaign_{campaign.id}_enrollment_{enrollment.id}"
    )
    response.append(connect)

    return str(response)


def generate_twiml_for_tts(
    db: Session,
    campaign: Campaign,
    message: CampaignMessage,
    contact: Contact,
    enrollment: CampaignContact
) -> str:
    """
    Generate TwiML for a simple TTS (text-to-speech) message
    """
    from twilio.twiml.voice_response import VoiceResponse, Gather

    response = VoiceResponse()

    # Personalize script
    from app.services.campaign_execution_service import personalize_message
    script = personalize_message(message.voice_script, contact, enrollment.lead if enrollment.lead_id else None)

    call_config = message.call_flow_config or {}

    # Check if we need to gather input
    if call_config.get('gather_input'):
        gather = Gather(
            num_digits=call_config.get('num_digits', 1),
            timeout=call_config.get('input_timeout', 5),
            action=f"{get_base_url()}/api/v1/voice-campaigns/{campaign.id}/gather/{enrollment.id}",
            method='POST'
        )
        gather.say(script, voice=message.tts_voice_id or 'alice')
        response.append(gather)

        # If no input, say goodbye
        response.say("We didn't receive any input. Goodbye!")
    else:
        # Simple message delivery
        response.say(script, voice=message.tts_voice_id or 'alice')

    # Check for voicemail message
    if call_config.get('voicemail_message'):
        response.say(call_config['voicemail_message'], voice=message.tts_voice_id or 'alice')

    return str(response)


def handle_call_status_callback(
    db: Session,
    campaign_id: int,
    call_sid: str,
    call_status: str,
    call_duration: Optional[int] = None,
    recording_url: Optional[str] = None,
    answered_by: Optional[str] = None
):
    """
    Handle Twilio call status callbacks
    """
    # Find the activity for this call
    activity = db.query(CampaignActivity).filter(
        CampaignActivity.campaign_id == campaign_id,
        CampaignActivity.external_id == call_sid
    ).first()

    if not activity:
        print(f"[VOICE CAMPAIGN] Activity not found for call {call_sid}")
        return

    # Update activity based on status
    if call_status == 'ringing':
        new_activity = CampaignActivity(
            campaign_id=activity.campaign_id,
            contact_id=activity.contact_id,
            lead_id=activity.lead_id,
            message_id=activity.message_id,
            activity_type=ActivityType.CALL_RINGING,
            external_id=call_sid
        )
        db.add(new_activity)

    elif call_status in ['in-progress', 'answered']:
        new_activity = CampaignActivity(
            campaign_id=activity.campaign_id,
            contact_id=activity.contact_id,
            lead_id=activity.lead_id,
            message_id=activity.message_id,
            activity_type=ActivityType.CALL_ANSWERED,
            external_id=call_sid,
            activity_data={
                'answered_by': answered_by
            }
        )
        db.add(new_activity)

        # Update enrollment
        enrollment = db.query(CampaignContact).filter(
            CampaignContact.campaign_id == campaign_id,
            CampaignContact.contact_id == activity.contact_id
        ).first()
        if enrollment:
            enrollment.calls_completed += 1

        # Check if voicemail
        if answered_by == 'machine_end_beep' or answered_by == 'machine_end_silence':
            voicemail_activity = CampaignActivity(
                campaign_id=activity.campaign_id,
                contact_id=activity.contact_id,
                lead_id=activity.lead_id,
                message_id=activity.message_id,
                activity_type=ActivityType.VOICEMAIL_DETECTED,
                external_id=call_sid
            )
            db.add(voicemail_activity)

            if enrollment:
                enrollment.voicemails_left += 1

    elif call_status == 'completed':
        new_activity = CampaignActivity(
            campaign_id=activity.campaign_id,
            contact_id=activity.contact_id,
            lead_id=activity.lead_id,
            message_id=activity.message_id,
            activity_type=ActivityType.CALL_COMPLETED,
            external_id=call_sid,
            activity_data={
                'duration': call_duration,
                'recording_url': recording_url
            }
        )
        db.add(new_activity)

        # Update enrollment duration
        enrollment = db.query(CampaignContact).filter(
            CampaignContact.campaign_id == campaign_id,
            CampaignContact.contact_id == activity.contact_id
        ).first()
        if enrollment and call_duration:
            enrollment.total_call_duration += call_duration

    elif call_status in ['busy', 'no-answer', 'failed', 'canceled']:
        activity_type_map = {
            'busy': ActivityType.CALL_BUSY,
            'no-answer': ActivityType.CALL_NO_ANSWER,
            'failed': ActivityType.CALL_FAILED,
            'canceled': ActivityType.CALL_FAILED
        }

        new_activity = CampaignActivity(
            campaign_id=activity.campaign_id,
            contact_id=activity.contact_id,
            lead_id=activity.lead_id,
            message_id=activity.message_id,
            activity_type=activity_type_map.get(call_status, ActivityType.CALL_FAILED),
            external_id=call_sid,
            activity_data={
                'status': call_status
            }
        )
        db.add(new_activity)

    db.commit()


def handle_gather_input(
    db: Session,
    campaign_id: int,
    enrollment_id: int,
    digits: str
) -> str:
    """
    Handle DTMF input gathered during a call
    """
    from twilio.twiml.voice_response import VoiceResponse

    # Get enrollment and message
    enrollment = db.query(CampaignContact).filter(
        CampaignContact.id == enrollment_id
    ).first()

    if not enrollment:
        response = VoiceResponse()
        response.say("Thank you for your response.")
        return str(response)

    message = db.query(CampaignMessage).filter(
        CampaignMessage.id == enrollment.current_message_id
    ).first()

    call_config = message.call_flow_config if message else {}

    # Record the input
    activity = CampaignActivity(
        campaign_id=campaign_id,
        contact_id=enrollment.contact_id,
        lead_id=enrollment.lead_id,
        message_id=message.id if message else None,
        activity_type=ActivityType.CONVERSATION_REPLIED,
        activity_data={
            'input': digits,
            'input_type': 'dtmf'
        }
    )
    db.add(activity)

    # Update enrollment
    enrollment.replies += 1

    db.commit()

    # Generate response based on input
    response = VoiceResponse()

    # Check for transfer option
    if call_config.get('transfer_to') and digits == call_config.get('transfer_digit', '0'):
        response.say("Please hold while we transfer you.")
        response.dial(call_config['transfer_to'])
    else:
        response.say("Thank you for your response. Goodbye!")

    return str(response)


def get_base_url() -> str:
    """Get the base URL for callbacks"""
    # This should come from settings/config
    return "https://your-domain.com"  # Replace with actual domain
