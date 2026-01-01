"""
Twilio Voice Service for handling voice call lifecycle and media stream processing.
"""
import logging
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from datetime import datetime

from app.models.voice_call import VoiceCall, CallStatus
from app.models.twilio_phone_number import TwilioPhoneNumber
from app.models.workflow_trigger import TriggerChannel
from app.services import (
    contact_service,
    conversation_session_service,
    chat_service,
)
from app.services import agent_execution_service
from app.services import workflow_trigger_service
from app.services.workflow_execution_service import WorkflowExecutionService
from app.schemas.chat_message import ChatMessageCreate

logger = logging.getLogger(__name__)


class TwilioVoiceService:
    """
    Manages Twilio voice call lifecycle and integration with AI agents/workflows.
    """

    def __init__(self, db: Session):
        self.db = db
        self.active_calls: Dict[str, Dict[str, Any]] = {}  # stream_sid -> call state

    def get_phone_number_config(self, to_number: str) -> Optional[TwilioPhoneNumber]:
        """
        Find the company/agent configuration for a Twilio phone number.

        Args:
            to_number: The Twilio phone number that was called (E.164 format)

        Returns:
            TwilioPhoneNumber config or None if not found
        """
        # Debug: List all phone numbers in database
        all_numbers = self.db.query(TwilioPhoneNumber).all()
        logger.info(f"Looking for phone number: '{to_number}'")
        logger.info(f"All phone numbers in DB: {[(n.phone_number, n.is_active) for n in all_numbers]}")

        result = self.db.query(TwilioPhoneNumber).filter(
            TwilioPhoneNumber.phone_number == to_number,
            TwilioPhoneNumber.is_active == True
        ).first()

        logger.info(f"Lookup result: {result}")
        return result

    async def handle_incoming_call(
        self,
        call_sid: str,
        from_number: str,
        to_number: str,
        caller_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Handle an incoming call - create records and return configuration.

        Args:
            call_sid: Twilio Call SID
            from_number: Caller's phone number
            to_number: Twilio number that was called
            caller_name: Caller name if available

        Returns:
            Configuration dict with company_id, agent_id, welcome_message, etc.
        """
        phone_config = self.get_phone_number_config(to_number)
        if not phone_config:
            logger.error(f"No configuration found for number: {to_number}")
            return {"error": "Phone number not configured"}

        company_id = phone_config.company_id
        agent_id = phone_config.default_agent_id

        # Get or create contact for this caller
        contact = contact_service.get_or_create_contact_for_channel(
            self.db,
            company_id=company_id,
            channel='twilio_voice',
            channel_identifier=from_number,
            name=caller_name
        )

        # Create conversation session using phone number for session continuity
        conversation_id = f"twilio_voice_{from_number}"
        session = conversation_session_service.get_or_create_session(
            self.db,
            conversation_id=conversation_id,
            workflow_id=None,
            contact_id=contact.id,
            channel='twilio_voice',
            company_id=company_id,
            agent_id=agent_id
        )

        # Reactivate session if it was previously resolved
        if session.status == 'resolved':
            session.status = 'active'
            session.is_client_connected = True
            self.db.commit()
            logger.info(f"Reactivated session {conversation_id} for returning caller")

        # Create voice call record
        voice_call = VoiceCall(
            call_sid=call_sid,
            from_number=from_number,
            to_number=to_number,
            company_id=company_id,
            agent_id=agent_id,
            integration_id=phone_config.integration_id,
            conversation_id=conversation_id,
            contact_id=contact.id,
            status=CallStatus.RINGING.value
        )
        self.db.add(voice_call)
        self.db.commit()

        logger.info(f"Created voice call record for {call_sid}, conversation: {conversation_id}")

        return {
            "call_sid": call_sid,
            "conversation_id": conversation_id,
            "company_id": company_id,
            "agent_id": agent_id,
            "welcome_message": phone_config.welcome_message,
            "language": phone_config.language
        }

    async def handle_call_connected(self, call_sid: str, stream_sid: str) -> Optional[VoiceCall]:
        """
        Called when Media Stream connects.

        Args:
            call_sid: Twilio Call SID
            stream_sid: Media Stream SID

        Returns:
            Updated VoiceCall record
        """
        voice_call = self.db.query(VoiceCall).filter(
            VoiceCall.call_sid == call_sid
        ).first()

        if voice_call:
            voice_call.stream_sid = stream_sid
            voice_call.status = CallStatus.IN_PROGRESS.value
            voice_call.answered_at = datetime.utcnow()
            self.db.commit()

            # Initialize call state in memory
            self.active_calls[stream_sid] = {
                "call_sid": call_sid,
                "voice_call_id": voice_call.id,
                "company_id": voice_call.company_id,
                "agent_id": voice_call.agent_id,
                "conversation_id": voice_call.conversation_id,
                "audio_buffer": bytearray(),
                "last_audio_time": None,
                "transcript_segments": [],
                "is_speaking": False
            }

            logger.info(f"Call connected: {call_sid}, stream: {stream_sid}")

        return voice_call

    async def handle_call_ended(self, call_sid: str) -> Optional[VoiceCall]:
        """
        Called when call ends.

        Args:
            call_sid: Twilio Call SID

        Returns:
            Updated VoiceCall record
        """
        voice_call = self.db.query(VoiceCall).filter(
            VoiceCall.call_sid == call_sid
        ).first()

        if voice_call:
            voice_call.status = CallStatus.COMPLETED.value
            voice_call.ended_at = datetime.utcnow()
            if voice_call.answered_at:
                voice_call.duration_seconds = (
                    voice_call.ended_at - voice_call.answered_at
                ).total_seconds()
            self.db.commit()

            # Mark conversation session as resolved
            if voice_call.conversation_id:
                session = conversation_session_service.get_session_by_conversation_id(
                    self.db, voice_call.conversation_id, voice_call.company_id
                )
                if session:
                    session.status = 'resolved'
                    session.is_client_connected = False
                    self.db.commit()
                    logger.info(f"Session {voice_call.conversation_id} marked as resolved")

            # Cleanup active call state
            if voice_call.stream_sid and voice_call.stream_sid in self.active_calls:
                del self.active_calls[voice_call.stream_sid]

            logger.info(f"Call ended: {call_sid}, duration: {voice_call.duration_seconds}s")

        return voice_call

    def get_call_state(self, stream_sid: str) -> Optional[Dict[str, Any]]:
        """Get the current state for an active call by stream_sid."""
        return self.active_calls.get(stream_sid)

    def update_call_state(self, stream_sid: str, updates: Dict[str, Any]) -> None:
        """Update the call state for an active stream."""
        if stream_sid in self.active_calls:
            self.active_calls[stream_sid].update(updates)

    async def process_speech(
        self,
        stream_sid: str,
        transcribed_text: str,
    ) -> Optional[str]:
        """
        Process transcribed speech through workflow/agent and return response text.

        Args:
            stream_sid: Media Stream SID
            transcribed_text: Transcribed text from STT

        Returns:
            AI response text or None
        """
        call_state = self.active_calls.get(stream_sid)
        if not call_state:
            logger.error(f"No call state found for stream: {stream_sid}")
            return None

        company_id = call_state["company_id"]
        agent_id = call_state["agent_id"]
        conversation_id = call_state["conversation_id"]

        # Save user message
        try:
            user_message = ChatMessageCreate(message=transcribed_text, message_type="voice")
            chat_service.create_chat_message(
                self.db, user_message, agent_id, conversation_id, company_id, "user"
            )
        except Exception as e:
            logger.error(f"Error saving user message: {e}")

        response_text = None

        # Try workflow trigger first
        try:
            workflow = await workflow_trigger_service.find_workflow_for_channel_message(
                db=self.db,
                channel=TriggerChannel.TWILIO_VOICE,
                company_id=company_id,
                message=transcribed_text,
                session_data={"session_id": conversation_id, "agent_id": agent_id}
            )

            if workflow:
                logger.info(f"Found workflow {workflow.id} for voice message")
                # Execute workflow
                workflow_exec = WorkflowExecutionService(self.db)
                result = await workflow_exec.execute_workflow(
                    user_message=transcribed_text,
                    conversation_id=conversation_id,
                    company_id=company_id,
                    workflow=workflow
                )
                if result and result.get("status") == "completed":
                    response_text = result.get("response", "")
                    logger.info(f"Workflow response: {response_text[:100]}...")
        except Exception as e:
            logger.error(f"Error in workflow processing: {e}")

        # Fallback to agent response if no workflow matched or workflow failed
        if not response_text and agent_id:
            try:
                response_text = await agent_execution_service.generate_agent_response(
                    self.db,
                    agent_id,
                    conversation_id,
                    conversation_id,  # broadcast_session_id
                    company_id,
                    transcribed_text
                )
                logger.info(f"Agent response: {str(response_text)[:100]}...")
            except Exception as e:
                logger.error(f"Error generating agent response: {e}")
                response_text = "I'm sorry, I encountered an error processing your request. Please try again."

        # Save agent response
        if response_text:
            try:
                agent_message = ChatMessageCreate(message=str(response_text), message_type="voice")
                chat_service.create_chat_message(
                    self.db, agent_message, agent_id, conversation_id, company_id, "agent"
                )
            except Exception as e:
                logger.error(f"Error saving agent message: {e}")

        # Store transcript segment
        if transcribed_text:
            call_state["transcript_segments"].append({
                "role": "user",
                "text": transcribed_text,
                "timestamp": datetime.utcnow().isoformat()
            })
        if response_text:
            call_state["transcript_segments"].append({
                "role": "agent",
                "text": str(response_text),
                "timestamp": datetime.utcnow().isoformat()
            })

        return str(response_text) if response_text else None

    def save_transcript(self, call_sid: str) -> None:
        """
        Save the full transcript to the voice call record.

        Args:
            call_sid: Twilio Call SID
        """
        voice_call = self.db.query(VoiceCall).filter(
            VoiceCall.call_sid == call_sid
        ).first()

        if voice_call and voice_call.stream_sid in self.active_calls:
            call_state = self.active_calls[voice_call.stream_sid]
            segments = call_state.get("transcript_segments", [])

            if segments:
                transcript_lines = []
                for segment in segments:
                    role = "User" if segment["role"] == "user" else "Agent"
                    transcript_lines.append(f"[{role}]: {segment['text']}")

                voice_call.full_transcript = "\n".join(transcript_lines)
                self.db.commit()
                logger.info(f"Saved transcript for call {call_sid}")


def get_voice_call_by_sid(db: Session, call_sid: str) -> Optional[VoiceCall]:
    """Get a voice call record by its Twilio Call SID."""
    return db.query(VoiceCall).filter(VoiceCall.call_sid == call_sid).first()


def get_voice_calls_by_company(
    db: Session,
    company_id: int,
    skip: int = 0,
    limit: int = 50
) -> list:
    """Get voice calls for a company with pagination."""
    return db.query(VoiceCall).filter(
        VoiceCall.company_id == company_id
    ).order_by(VoiceCall.started_at.desc()).offset(skip).limit(limit).all()
