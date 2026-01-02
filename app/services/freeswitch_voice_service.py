"""
FreeSWITCH Voice Service for handling voice call lifecycle and media stream processing.
"""
import logging
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from datetime import datetime

from app.models.voice_call import VoiceCall, CallStatus
from app.models.freeswitch_phone_number import FreeSwitchPhoneNumber
from app.models.workflow_trigger import TriggerChannel
from app.services import (
    contact_service,
    conversation_session_service,
    chat_service,
    memory_service,
)
from app.services import agent_execution_service
from app.services import workflow_trigger_service
from app.services.workflow_execution_service import WorkflowExecutionService
from app.schemas.chat_message import ChatMessageCreate

logger = logging.getLogger(__name__)


class FreeSwitchVoiceService:
    """
    Manages FreeSWITCH voice call lifecycle and integration with AI agents/workflows.
    """

    def __init__(self, db: Session):
        self.db = db
        self.active_calls: Dict[str, Dict[str, Any]] = {}  # call_uuid -> call state

    def get_phone_number_config(self, destination_number: str) -> Optional[FreeSwitchPhoneNumber]:
        """
        Find the company/agent configuration for a FreeSWITCH extension/number.

        Args:
            destination_number: The number/extension that was called

        Returns:
            FreeSwitchPhoneNumber config or None if not found
        """
        return self.db.query(FreeSwitchPhoneNumber).filter(
            FreeSwitchPhoneNumber.phone_number == destination_number,
            FreeSwitchPhoneNumber.is_active == True
        ).first()

    async def handle_incoming_call(
        self,
        call_uuid: str,
        from_number: str,
        to_number: str,
        caller_name: Optional[str] = None,
        channel_data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Handle an incoming call - create records and return configuration.

        Args:
            call_uuid: FreeSWITCH Call UUID
            from_number: Caller's phone number
            to_number: Number/extension that was called
            caller_name: Caller name if available
            channel_data: Additional FreeSWITCH channel variables

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
            channel='freeswitch',
            channel_identifier=from_number,
            name=caller_name
        )

        # Create conversation session using phone number for session continuity
        conversation_id = f"freeswitch_{from_number}"
        session = conversation_session_service.get_or_create_session(
            self.db,
            conversation_id=conversation_id,
            workflow_id=None,
            contact_id=contact.id,
            channel='freeswitch',
            company_id=company_id,
            agent_id=agent_id
        )

        # For voice calls, ALWAYS clear workflow state for fresh start on each new call
        # Voice calls should not resume from previous workflow state
        session.next_step_id = None
        session.context = {}
        session.workflow_id = None
        session.is_client_connected = True

        # Reactivate session if it was previously resolved
        if session.status == 'resolved':
            session.status = 'active'
            logger.info(f"Reactivated session {conversation_id} for returning caller")

        self.db.commit()

        # Clear workflow memories for fresh start
        if agent_id:
            memory_service.delete_all_memories(self.db, agent_id, conversation_id)
            logger.info(f"Cleared workflow state for session {conversation_id}")

        # Create voice call record (reusing VoiceCall model)
        voice_call = VoiceCall(
            call_sid=call_uuid,  # Using call_sid field for UUID
            from_number=from_number,
            to_number=to_number,
            company_id=company_id,
            agent_id=agent_id,
            conversation_id=conversation_id,
            contact_id=contact.id,
            status=CallStatus.RINGING.value,
            direction="inbound"
        )
        self.db.add(voice_call)
        self.db.commit()

        # Initialize call state in memory
        self.active_calls[call_uuid] = {
            "call_uuid": call_uuid,
            "voice_call_id": voice_call.id,
            "company_id": company_id,
            "agent_id": agent_id,
            "conversation_id": conversation_id,
            "sample_rate": phone_config.sample_rate,
            "audio_buffer": bytearray(),
            "last_audio_time": None,
            "transcript_segments": [],
            "is_speaking": False
        }

        logger.info(f"Created voice call record for {call_uuid}, conversation: {conversation_id}")

        return {
            "call_uuid": call_uuid,
            "conversation_id": conversation_id,
            "company_id": company_id,
            "agent_id": agent_id,
            "welcome_message": phone_config.welcome_message,
            "language": phone_config.language,
            "sample_rate": phone_config.sample_rate,
            "audio_format": phone_config.audio_format
        }

    async def handle_call_connected(self, call_uuid: str) -> Optional[VoiceCall]:
        """
        Called when audio stream connects.

        Args:
            call_uuid: FreeSWITCH Call UUID

        Returns:
            Updated VoiceCall record
        """
        voice_call = self.db.query(VoiceCall).filter(
            VoiceCall.call_sid == call_uuid
        ).first()

        if voice_call:
            voice_call.stream_sid = call_uuid  # For FreeSWITCH, use same UUID
            voice_call.status = CallStatus.IN_PROGRESS.value
            voice_call.answered_at = datetime.utcnow()
            self.db.commit()

            logger.info(f"Call connected: {call_uuid}")

        return voice_call

    async def handle_call_ended(self, call_uuid: str, hangup_cause: Optional[str] = None) -> Optional[VoiceCall]:
        """
        Called when call ends.

        Args:
            call_uuid: FreeSWITCH Call UUID
            hangup_cause: FreeSWITCH hangup cause

        Returns:
            Updated VoiceCall record
        """
        voice_call = self.db.query(VoiceCall).filter(
            VoiceCall.call_sid == call_uuid
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

            # Save transcript before cleanup
            self.save_transcript(call_uuid)

            # Cleanup active call state
            if call_uuid in self.active_calls:
                del self.active_calls[call_uuid]

            logger.info(f"Call ended: {call_uuid}, cause: {hangup_cause}, duration: {voice_call.duration_seconds}s")

        return voice_call

    def get_call_state(self, call_uuid: str) -> Optional[Dict[str, Any]]:
        """Get the current state for an active call by UUID."""
        return self.active_calls.get(call_uuid)

    def update_call_state(self, call_uuid: str, updates: Dict[str, Any]) -> None:
        """Update the call state for an active call."""
        if call_uuid in self.active_calls:
            self.active_calls[call_uuid].update(updates)

    async def process_speech(
        self,
        call_uuid: str,
        transcribed_text: str,
    ) -> Optional[str]:
        """
        Process transcribed speech through workflow/agent and return response text.

        Args:
            call_uuid: Call UUID
            transcribed_text: Transcribed text from STT

        Returns:
            AI response text or None
        """
        call_state = self.active_calls.get(call_uuid)
        if not call_state:
            logger.error(f"No call state found for UUID: {call_uuid}")
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
        workflow_triggered = False  # Track if workflow was triggered

        # Try workflow trigger first
        try:
            workflow = await workflow_trigger_service.find_workflow_for_channel_message(
                db=self.db,
                channel=TriggerChannel.FREESWITCH,
                company_id=company_id,
                message=transcribed_text,
                session_data={"session_id": conversation_id, "agent_id": agent_id}
            )

            if workflow:
                workflow_triggered = True  # Mark workflow as triggered
                logger.info(f"Found workflow {workflow.id} for voice message")
                # Execute workflow
                workflow_exec = WorkflowExecutionService(self.db)
                result = await workflow_exec.execute_workflow(
                    user_message=transcribed_text,
                    conversation_id=conversation_id,
                    company_id=company_id,
                    workflow=workflow
                )
                # Extract response regardless of status (workflow may have response nodes before pausing)
                if result:
                    response_text = result.get("response", "")
                    if response_text:
                        logger.info(f"Workflow response ({result.get('status')}): {response_text[:100]}...")
        except Exception as e:
            logger.error(f"Error in workflow processing: {e}")

        # Fallback to agent response ONLY if no workflow was triggered
        if not workflow_triggered and not response_text and agent_id:
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

    def save_transcript(self, call_uuid: str) -> None:
        """
        Save the full transcript to the voice call record.

        Args:
            call_uuid: FreeSWITCH Call UUID
        """
        voice_call = self.db.query(VoiceCall).filter(
            VoiceCall.call_sid == call_uuid
        ).first()

        if voice_call and call_uuid in self.active_calls:
            call_state = self.active_calls[call_uuid]
            segments = call_state.get("transcript_segments", [])

            if segments:
                transcript_lines = []
                for segment in segments:
                    role = "User" if segment["role"] == "user" else "Agent"
                    transcript_lines.append(f"[{role}]: {segment['text']}")

                voice_call.full_transcript = "\n".join(transcript_lines)
                self.db.commit()
                logger.info(f"Saved transcript for call {call_uuid}")


def get_freeswitch_phone_numbers_by_company(
    db: Session,
    company_id: int,
    skip: int = 0,
    limit: int = 50
) -> list:
    """Get FreeSWITCH phone numbers for a company with pagination."""
    return db.query(FreeSwitchPhoneNumber).filter(
        FreeSwitchPhoneNumber.company_id == company_id
    ).offset(skip).limit(limit).all()
