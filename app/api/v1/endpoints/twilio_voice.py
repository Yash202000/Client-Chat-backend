"""
Twilio Voice API endpoints for handling incoming calls and media streams.
"""
from fastapi import APIRouter, Request, Depends, HTTPException, WebSocket, WebSocketDisconnect, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session
import json
import asyncio
import logging
import base64
from typing import Optional

from pydantic import BaseModel
from app.core.dependencies import get_db, get_current_user
from app.core.config import settings
from app.models.user import User
from app.models.twilio_phone_number import TwilioPhoneNumber
from app.models.voice_call import VoiceCall, CallStatus
from app.models.contact import Contact
from app.services.twilio_voice_service import TwilioVoiceService, get_voice_calls_by_company
from app.services.audio_conversion_service import AudioConversionService
from app.services.stt_service import OpenAISTTService
from app.services.tts_service import OpenAITTSService
from app.services.vad_service import SileroVADService, VADEvent, VADResult
from app.services.openai_realtime_service import (
    OpenAIRealtimeService,
    convert_mulaw_8k_to_pcm_24k,
    convert_pcm_24k_to_mulaw_8k,
)
from app.services import credential_service, integration_service, agent_service, chat_service, workflow_trigger_service
from app.services.call_recording_service import upload_recording, mulaw_to_pcm16
from app.services.agent_execution_service import _get_tools_for_agent
from app.services.tool_execution_service import execute_tool
from app.services.connection_manager import manager
from app.services.workflow_execution_service import WorkflowExecutionService
from app.models.workflow_trigger import TriggerChannel
from app.schemas.chat_message import ChatMessageCreate
from app.models.integration import Integration
from twilio.rest import Client as TwilioClient
from app.schemas.twilio_voice import (
    TwilioPhoneNumberCreate,
    TwilioPhoneNumberUpdate,
    TwilioPhoneNumberResponse,
    VoiceCallResponse,
    VoiceCallListResponse,
)

router = APIRouter()
logger = logging.getLogger(__name__)

# Configuration - Silero VAD settings (matching LiveKit defaults)
VAD_THRESHOLD = float(getattr(settings, 'VAD_THRESHOLD', 0.5))  # Speech probability threshold
VAD_MIN_SPEECH_MS = int(getattr(settings, 'VAD_MIN_SPEECH_MS', 50))  # Minimum speech duration (ms) - LiveKit: 0.05s
VAD_MIN_SILENCE_MS = int(getattr(settings, 'VAD_MIN_SILENCE_MS', 550))  # Minimum silence to end speech (ms) - LiveKit: 0.55s
MIN_AUDIO_LENGTH = 3200  # Minimum audio buffer size (~0.4 seconds at 8kHz)
MAX_BUFFER_SECONDS = 8  # Maximum seconds to buffer before forcing processing


def get_twiml_response(content: str, content_type: str = "application/xml") -> Response:
    """Helper to return TwiML responses."""
    return Response(content=content, media_type=content_type)


# --- Webhook Endpoints (No Auth - Twilio Signature Validation in Production) ---

@router.get("/webhook/voice")
async def webhook_voice_info():
    """
    GET handler for webhook URL - returns status info.
    Useful for verifying the webhook URL is accessible.
    Twilio will send POST requests when a call comes in.
    """
    return {
        "status": "ok",
        "message": "Twilio Voice Webhook endpoint is active. Twilio will send POST requests here when calls come in.",
        "method_expected": "POST"
    }


@router.post("/webhook/voice")
async def handle_incoming_call(request: Request, db: Session = Depends(get_db)):
    """
    Twilio webhook for incoming voice calls.
    Returns TwiML to connect to Media Streams.
    """
    form_data = await request.form()

    call_sid = form_data.get("CallSid")
    from_number = form_data.get("From")
    to_number = form_data.get("To")
    caller_name = form_data.get("CallerName")

    logger.info(f"=== INCOMING CALL WEBHOOK TRIGGERED ===")
    logger.info(f"Incoming call: {call_sid} from {from_number} to {to_number}")
    logger.info(f"To number (raw): '{to_number}' (type: {type(to_number)}, len: {len(to_number) if to_number else 0})")

    voice_service = TwilioVoiceService(db)
    call_config = await voice_service.handle_incoming_call(
        call_sid=call_sid,
        from_number=from_number,
        to_number=to_number,
        caller_name=caller_name
    )

    if "error" in call_config:
        # Return TwiML that rejects the call
        twiml = '''<?xml version="1.0" encoding="UTF-8"?>
        <Response>
            <Say voice="Polly.Joanna">Sorry, this number is not configured. Goodbye.</Say>
            <Hangup/>
        </Response>'''
        return get_twiml_response(twiml)

    # Build WebSocket URL for Media Streams
    # Prioritize: PUBLIC_HOST setting > X-Forwarded-Host header > Host header > request hostname
    ws_host = getattr(settings, 'PUBLIC_HOST', None)
    if not ws_host:
        ws_host = request.headers.get('X-Forwarded-Host') or request.headers.get('Host') or request.url.hostname

    # Strip any protocol prefix from host (in case it includes http:// or https://)
    if ws_host:
        ws_host = ws_host.replace('https://', '').replace('http://', '').rstrip('/')

    # Get scheme - prioritize X-Forwarded-Proto for reverse proxy setups
    forwarded_proto = request.headers.get('X-Forwarded-Proto', request.url.scheme)
    ws_scheme = "wss" if forwarded_proto == "https" else "ws"

    # For production (non-localhost), always force wss - Twilio requires secure WebSockets
    if ws_host and not ws_host.startswith('localhost') and not ws_host.startswith('127.'):
        ws_scheme = "wss"

    ws_url = f"{ws_scheme}://{ws_host}/api/v1/twilio/media-stream/{call_sid}"

    # Debug logging for WebSocket URL construction
    logger.info(f"PUBLIC_HOST setting: {getattr(settings, 'PUBLIC_HOST', None)}")
    logger.info(f"ws_host after processing: {ws_host}")
    logger.info(f"WebSocket URL constructed: {ws_url}")
    logger.info(f"Request headers - Host: {request.headers.get('Host')}, X-Forwarded-Host: {request.headers.get('X-Forwarded-Host')}, X-Forwarded-Proto: {request.headers.get('X-Forwarded-Proto')}")

    # Build TwiML with Media Streams
    welcome_message = call_config.get("welcome_message") or "Hello, how can I help you today?"

    twiml = f'''<?xml version="1.0" encoding="UTF-8"?>
    <Response>
        <Say voice="Polly.Joanna">{welcome_message}</Say>
        <Connect>
            <Stream url="{ws_url}">
                <Parameter name="conversation_id" value="{call_config['conversation_id']}" />
                <Parameter name="company_id" value="{call_config['company_id']}" />
                <Parameter name="agent_id" value="{call_config.get('agent_id', '')}" />
            </Stream>
        </Connect>
    </Response>'''

    logger.info(f"Returning TwiML with stream URL: {ws_url}")
    return get_twiml_response(twiml)


@router.get("/webhook/voice/status")
async def webhook_status_info():
    """GET handler for status webhook URL verification."""
    return {
        "status": "ok",
        "message": "Twilio Call Status Webhook endpoint is active.",
        "method_expected": "POST"
    }


@router.post("/webhook/voice/status")
async def handle_call_status(request: Request, db: Session = Depends(get_db)):
    """
    Twilio webhook for call status updates.
    """
    from datetime import datetime as _dt
    from app.services import sms_service as _sms_service

    form_data = await request.form()

    call_sid = form_data.get("CallSid")
    call_status = form_data.get("CallStatus")
    call_duration_str = form_data.get("CallDuration", "0")

    logger.info(f"Call status update: {call_sid} -> {call_status}")

    voice_service = TwilioVoiceService(db)

    if call_status in ["completed", "failed", "busy", "no-answer", "canceled"]:
        voice_service.save_transcript(call_sid)
        await voice_service.handle_call_ended(call_sid)

        # CSAT survey — send SMS when call completes with duration > 30s
        if call_status == "completed":
            try:
                duration = int(call_duration_str or "0")
                if duration > 30:
                    call = db.query(VoiceCall).filter(VoiceCall.call_sid == call_sid).first()
                    if call and call.contact_id:
                        contact = db.query(Contact).filter(Contact.id == call.contact_id).first()
                        if contact and contact.phone_number:
                            _sms_service.send_sms(
                                to=contact.phone_number,
                                body="How would you rate your recent call? Reply with a number from 1 (poor) to 5 (excellent).",
                                db=db,
                                company_id=call.company_id,
                            )
                            call.csat_sent_at = _dt.utcnow()
                            db.commit()
                            logger.info(f"[CSAT] Sent survey SMS for call {call_sid}")
            except Exception as csat_err:
                logger.warning(f"[CSAT] Failed to send survey for {call_sid}: {csat_err}")

    return Response(status_code=200)


# --- OpenAI Realtime Mode Handler ---

async def handle_realtime_mode(
    websocket: WebSocket,
    stream_sid: str,
    agent,
    openai_api_key: str,
    voice_service: TwilioVoiceService,
    db: Session,
    conversation_id: str,
    company_id: int,
):
    """
    Handle voice call using OpenAI Realtime API for ultra-low latency.
    Bridges Twilio Media Stream WebSocket to OpenAI Realtime API WebSocket.
    """
    logger.info(f"Starting OpenAI Realtime mode for stream {stream_sid}")
    agent_id = agent.id if agent else None

    # Get agent tools for function calling
    tools = []
    try:
        tool_definitions = await _get_tools_for_agent(agent)
        # Convert to Realtime API format
        for tool_def in tool_definitions:
            if tool_def.get("type") == "function":
                func = tool_def["function"]
                tools.append({
                    "type": "function",
                    "name": func["name"],
                    "description": func.get("description", ""),
                    "parameters": func.get("parameters", {"type": "object", "properties": {}}),
                })
        logger.info(f"Configured {len(tools)} tools for Realtime API")
    except Exception as e:
        logger.error(f"Error getting agent tools: {e}")

    # Initialize Realtime service
    realtime = OpenAIRealtimeService(
        model=settings.OPENAI_REALTIME_MODEL,
        voice=settings.OPENAI_REALTIME_VOICE,
        system_prompt=agent.prompt if agent else None,
        tools=tools,
    )

    # Connect to OpenAI Realtime API
    if not await realtime.connect():
        logger.error("Failed to connect to OpenAI Realtime API, falling back to standard mode")
        return False  # Signal to fall back to standard mode

    # Track transcripts for saving
    transcripts = []

    # Flag to track when workflow has taken over (skip OpenAI response)
    workflow_active = False

    async def send_workflow_tts_response(text: str):
        """Convert workflow text response to audio and send to Twilio."""
        # Note: We do NOT reset workflow_active here - it stays True until
        # the next user speech cycle begins (on speech_started event).
        # This ensures any lingering OpenAI responses are discarded.
        try:
            tts_service = OpenAITTSService(api_key=openai_api_key)
            pcm_audio = await tts_service.text_to_speech_pcm(text)

            # Convert PCM 24kHz to mulaw 8kHz for Twilio
            mulaw_bytes = convert_pcm_24k_to_mulaw_8k(pcm_audio)

            # Send in chunks (640 bytes = 40ms at 8kHz mulaw)
            chunk_size = 640
            for i in range(0, len(mulaw_bytes), chunk_size):
                chunk = mulaw_bytes[i:i+chunk_size]
                mulaw_b64 = base64.b64encode(chunk).decode("utf-8")
                media_message = {
                    "event": "media",
                    "streamSid": stream_sid,
                    "media": {"payload": mulaw_b64}
                }
                await websocket.send_json(media_message)
                await asyncio.sleep(0.04)  # 40ms between chunks

            logger.info(f"Sent workflow TTS response: {text[:50]}...")
        except Exception as e:
            logger.error(f"Error sending workflow TTS response: {e}")

    async def forward_twilio_to_openai():
        """Forward audio from Twilio to OpenAI Realtime API."""
        try:
            while True:
                message = await websocket.receive_text()
                data = json.loads(message)
                event_type = data.get("event")

                if event_type == "media":
                    media_data = data.get("media", {})
                    payload = media_data.get("payload", "")
                    if payload:
                        # Decode mulaw and convert to PCM 24kHz
                        mulaw_bytes = base64.b64decode(payload)
                        pcm_24k = convert_mulaw_8k_to_pcm_24k(mulaw_bytes)
                        await realtime.send_audio(pcm_24k)

                elif event_type == "stop":
                    logger.info("Twilio stream stopped")
                    break

        except WebSocketDisconnect:
            logger.info("Twilio WebSocket disconnected")
        except Exception as e:
            logger.error(f"Error forwarding Twilio to OpenAI: {e}")

    async def forward_openai_to_twilio():
        """Forward audio from OpenAI Realtime API to Twilio."""
        nonlocal workflow_active

        # Audio buffering for workflow priority
        # We buffer ALL OpenAI audio for each response until we receive the user transcript
        # The transcript may arrive before, during, or after the response audio
        audio_buffer = []
        awaiting_transcript = False
        current_response_id = None  # Track which response we're buffering

        async def flush_audio_buffer():
            """Forward all buffered audio to Twilio."""
            nonlocal audio_buffer
            for chunk in audio_buffer:
                mulaw_bytes = convert_pcm_24k_to_mulaw_8k(chunk)
                mulaw_b64 = base64.b64encode(mulaw_bytes).decode("utf-8")
                await websocket.send_json({
                    "event": "media",
                    "streamSid": stream_sid,
                    "media": {"payload": mulaw_b64}
                })
            audio_buffer = []

        try:
            async for event in realtime.receive_events():
                # Detect when user starts speaking - we'll need to check for workflow
                if event.type == "input_audio_buffer.speech_started":
                    awaiting_transcript = True
                    audio_buffer = []
                    current_response_id = None
                    # Reset workflow_active for new speech cycle - allows fresh workflow check
                    workflow_active = False
                    logger.debug("User speech started, will buffer OpenAI response")

                # Detect when OpenAI starts generating a response - buffer from here
                if event.type == "response.created":
                    # If we're still waiting for user transcript, buffer this response
                    if awaiting_transcript:
                        current_response_id = event.data.get("response", {}).get("id")
                        logger.debug(f"Response created while awaiting transcript, buffering: {current_response_id}")

                # Handle audio output with buffering
                audio_bytes = realtime.extract_audio_delta(event)
                if audio_bytes:
                    if workflow_active:
                        pass  # Skip - workflow is handling response
                    elif awaiting_transcript:
                        # Buffer audio until we check for workflow trigger
                        audio_buffer.append(audio_bytes)
                    else:
                        # No pending workflow check, forward immediately
                        mulaw_bytes = convert_pcm_24k_to_mulaw_8k(audio_bytes)
                        mulaw_b64 = base64.b64encode(mulaw_bytes).decode("utf-8")

                        media_message = {
                            "event": "media",
                            "streamSid": stream_sid,
                            "media": {"payload": mulaw_b64}
                        }
                        await websocket.send_json(media_message)

                # Handle function calls (only if workflow not active)
                func_call = realtime.extract_function_call(event)
                if func_call and not workflow_active:
                    logger.info(f"Realtime function call: {func_call.name}")
                    try:
                        # Execute the tool
                        import json as json_module
                        args = json_module.loads(func_call.arguments)
                        result = await execute_tool(
                            db=db,
                            tool_name=func_call.name,
                            parameters=args,
                            session_id=stream_sid or "",
                            company_id=agent.company_id if agent else 0,
                        )
                        result_str = json_module.dumps(result) if isinstance(result, dict) else str(result)
                        await realtime.submit_function_result(func_call.call_id, result_str)
                        logger.info(f"Function {func_call.name} completed")
                    except Exception as e:
                        logger.error(f"Error executing function {func_call.name}: {e}")
                        await realtime.submit_function_result(func_call.call_id, f"Error: {str(e)}")

                # Handle transcripts - save to DB and broadcast
                transcript = realtime.extract_transcript(event)
                if transcript:
                    role, text = transcript
                    transcripts.append({"role": role, "text": text})
                    logger.info(f"Transcript [{role}]: {text[:50]}...")

                    # Check for workflow trigger on user messages
                    if role == "user":
                        # Got user transcript, stop buffering
                        awaiting_transcript = False

                        try:
                            workflow = await workflow_trigger_service.find_workflow_for_channel_message(
                                db=db,
                                channel=TriggerChannel.TWILIO_VOICE,
                                company_id=company_id,
                                message=text,
                                session_data={"session_id": conversation_id, "agent_id": agent_id}
                            )

                            if workflow:
                                logger.info(f"Workflow {workflow.id} matched for voice message: {text[:30]}...")
                                workflow_active = True

                                # Discard buffered OpenAI audio - workflow will respond instead
                                discarded_count = len(audio_buffer)
                                audio_buffer.clear()
                                logger.info(f"Discarded {discarded_count} buffered OpenAI audio chunks")

                                # Cancel any in-progress OpenAI response to prevent it from speaking
                                await realtime.cancel_response()
                                logger.info("Cancelled OpenAI response for workflow execution")

                                # Execute workflow
                                workflow_exec = WorkflowExecutionService(db)
                                result = await workflow_exec.execute_workflow(
                                    user_message=text,
                                    conversation_id=conversation_id,
                                    company_id=company_id,
                                    workflow=workflow
                                )

                                if result:
                                    status = result.get("status")
                                    response_text = result.get("response", "")

                                    # Handle response for any status that has one
                                    if response_text:
                                        # Save workflow response to DB
                                        msg_create = ChatMessageCreate(message=response_text, message_type="voice")
                                        saved_msg = chat_service.create_chat_message(
                                            db, msg_create, agent_id, conversation_id, company_id, "agent"
                                        )

                                        # Broadcast workflow response
                                        if saved_msg:
                                            broadcast_msg = {
                                                "type": "message",
                                                "message": {
                                                    "id": saved_msg.id,
                                                    "message": response_text,
                                                    "sender": "agent",
                                                    "message_type": "voice",
                                                    "timestamp": saved_msg.timestamp.isoformat() if saved_msg.timestamp else None,
                                                }
                                            }
                                            await manager.broadcast_to_session(
                                                conversation_id, json.dumps(broadcast_msg), "agent"
                                            )

                                        # Send workflow response via TTS
                                        await send_workflow_tts_response(response_text)
                                        logger.info(f"Sent TTS for workflow response ({status}): {response_text[:50]}...")

                                    # Also handle prompt text for paused_for_prompt status
                                    if status == "paused_for_prompt":
                                        prompt_data = result.get("prompt", {})
                                        prompt_text = prompt_data.get("text", "")
                                        options = prompt_data.get("options", [])

                                        # Format prompt with options for voice
                                        # Handle options as list of dicts, list of strings, or comma-separated string
                                        option_names = []
                                        if options:
                                            if isinstance(options, str):
                                                option_names = [o.strip() for o in options.split(',')]
                                            elif isinstance(options, list) and options:
                                                if isinstance(options[0], dict):
                                                    option_names = [o.get('label', o.get('value', str(o))) for o in options]
                                                else:
                                                    option_names = [str(o) for o in options]

                                        if option_names:
                                            full_prompt_text = f"{prompt_text}. Your options are: {', '.join(option_names)}"
                                        else:
                                            full_prompt_text = prompt_text

                                        if full_prompt_text and full_prompt_text != response_text:
                                            # Send prompt text via TTS as well
                                            await send_workflow_tts_response(full_prompt_text)
                                            logger.info(f"Sent TTS for prompt: {full_prompt_text[:50]}...")

                                    continue  # Skip OpenAI response processing
                                else:
                                    logger.warning(f"Workflow returned no result")
                                    workflow_active = False
                            else:
                                # No workflow matched - forward buffered OpenAI audio
                                if audio_buffer:
                                    logger.info(f"No workflow, forwarding {len(audio_buffer)} buffered audio chunks")
                                    await flush_audio_buffer()
                        except Exception as e:
                            logger.error(f"Error checking/executing workflow trigger: {e}")
                            import traceback
                            traceback.print_exc()
                            # Only forward buffered audio if no workflow was matched
                            # If workflow was matched (workflow_active=True), keep it True to block OpenAI responses
                            if not workflow_active:
                                if audio_buffer:
                                    await flush_audio_buffer()

                    # Save message to database
                    # - Always save user messages
                    # - Skip OpenAI assistant responses when workflow is active (workflow already responded)
                    if role == "assistant" and workflow_active:
                        logger.debug(f"Skipping OpenAI assistant transcript (workflow active): {text[:50]}...")
                        continue

                    try:
                        sender = "user" if role == "user" else "agent"
                        msg_create = ChatMessageCreate(message=text, message_type="voice")
                        saved_msg = chat_service.create_chat_message(
                            db, msg_create, agent_id, conversation_id, company_id, sender
                        )

                        # Broadcast to frontend via WebSocket
                        if saved_msg:
                            broadcast_msg = {
                                "type": "message",
                                "message": {
                                    "id": saved_msg.id,
                                    "message": text,
                                    "sender": sender,
                                    "message_type": "voice",
                                    "timestamp": saved_msg.timestamp.isoformat() if saved_msg.timestamp else None,
                                }
                            }
                            await manager.broadcast_to_session(
                                conversation_id, json.dumps(broadcast_msg), sender
                            )
                            logger.debug(f"Broadcast {sender} message to session {conversation_id}")
                    except Exception as e:
                        logger.error(f"Error saving/broadcasting transcript: {e}")

                # Handle errors
                if event.type == "error":
                    logger.error(f"Realtime API error: {event.data}")

        except Exception as e:
            logger.error(f"Error forwarding OpenAI to Twilio: {e}")

    try:
        # Run both directions concurrently
        await asyncio.gather(
            forward_twilio_to_openai(),
            forward_openai_to_twilio(),
        )
    finally:
        await realtime.disconnect()
        logger.info(f"Realtime mode ended, transcripts: {len(transcripts)}")

    return True  # Success


# --- Media Stream WebSocket ---

@router.websocket("/media-stream/{call_sid}")
async def twilio_media_stream(
    websocket: WebSocket,
    call_sid: str,
    db: Session = Depends(get_db)
):
    """
    WebSocket endpoint for Twilio Media Streams.
    Handles real-time audio streaming, STT, AI response, and TTS.
    """
    await websocket.accept()

    logger.info(f"Media stream WebSocket connected for call: {call_sid}")

    voice_service = TwilioVoiceService(db)
    audio_converter = AudioConversionService()

    # State variables
    openai_api_key = None
    company_id = None
    agent_id = None
    stream_sid = None

    # Audio buffering for VAD (Voice Activity Detection)
    audio_buffer = bytearray()
    buffer_start_time = None
    is_processing = False
    is_speech_active = False

    # Full-call recording buffer (mulaw bytes — converted to PCM on upload)
    recording_buffer = bytearray()

    # Initialize Silero VAD
    vad_service = SileroVADService(
        threshold=VAD_THRESHOLD,
        min_speech_duration_ms=VAD_MIN_SPEECH_MS,
        min_silence_duration_ms=VAD_MIN_SILENCE_MS,
        sample_rate=8000,  # Twilio uses 8kHz mulaw
    )
    logger.info(f"Silero VAD initialized for call {call_sid}")

    async def process_audio_buffer():
        """Process accumulated audio through STT and get AI response."""
        nonlocal audio_buffer, is_processing, buffer_start_time

        if not audio_buffer or is_processing or len(audio_buffer) < MIN_AUDIO_LENGTH:
            logger.debug(f"Skipping process_audio_buffer: buffer={len(audio_buffer)}, processing={is_processing}")
            return

        logger.info(f"Processing audio buffer: {len(audio_buffer)} bytes")
        is_processing = True
        buffer_start_time = None  # Reset buffer timer
        try:
            # Convert accumulated mulaw to PCM for Whisper
            pcm_16k = audio_converter.buffer_to_whisper_format(audio_buffer)
            logger.info(f"Converted to PCM: {len(pcm_16k)} bytes")

            # Transcribe with Whisper
            if not openai_api_key:
                logger.error("No OpenAI API key available for STT")
                return

            stt_service = OpenAISTTService(api_key=openai_api_key)
            logger.info("Calling Whisper STT...")
            result = await stt_service.transcribe_pcm(pcm_16k)
            logger.info(f"STT result: {result}")

            transcribed_text = result.get("text", "").strip()

            if transcribed_text:
                logger.info(f"Transcribed: {transcribed_text}")

                # Get AI response
                response_text = await voice_service.process_speech(
                    stream_sid=stream_sid,
                    transcribed_text=transcribed_text,
                )

                if response_text:
                    logger.info(f"AI Response: {response_text[:100]}...")
                    # Convert response to speech and stream back
                    await stream_tts_response(response_text)

            audio_buffer.clear()

        except Exception as e:
            logger.error(f"Error processing audio: {e}")
        finally:
            is_processing = False

    async def stream_tts_response(text: str):
        """Generate TTS and stream back to Twilio."""
        try:
            # Check if WebSocket is still connected
            if websocket.client_state.name != "CONNECTED":
                logger.warning(f"Cannot stream TTS - WebSocket state is {websocket.client_state.name}")
                return

            if not openai_api_key:
                logger.error("Cannot stream TTS - OpenAI API key not available")
                return

            logger.info(f"Starting TTS for: {text[:50]}...")
            tts_service = OpenAITTSService(api_key=openai_api_key)

            # Get PCM audio from TTS
            pcm_audio = await tts_service.text_to_speech_pcm(text)
            logger.info(f"TTS generated {len(pcm_audio)} bytes of PCM audio")

            # Convert to Twilio format (mulaw 8kHz)
            mulaw_b64 = audio_converter.tts_to_twilio(pcm_audio, tts_sample_rate=24000)

            # Send to Twilio in chunks
            chunks = audio_converter.chunk_audio_for_streaming(mulaw_b64, chunk_size=8000)
            logger.info(f"Sending {len(chunks)} audio chunks to Twilio")

            for chunk in chunks:
                # Check WebSocket state before each send
                if websocket.client_state.name != "CONNECTED":
                    logger.warning("WebSocket disconnected during TTS streaming")
                    return

                media_message = {
                    "event": "media",
                    "streamSid": stream_sid,
                    "media": {
                        "payload": chunk
                    }
                }
                await websocket.send_json(media_message)
                await asyncio.sleep(0.05)  # Small delay between chunks

            # Send mark to indicate end of audio
            mark_message = {
                "event": "mark",
                "streamSid": stream_sid,
                "mark": {
                    "name": "response_complete"
                }
            }
            await websocket.send_json(mark_message)
            logger.info("TTS streaming completed successfully")

        except Exception as e:
            logger.error(f"Error streaming TTS: {e}", exc_info=True)

    async def check_buffer_timeout():
        """Background task to enforce max buffer time."""
        nonlocal buffer_start_time
        check_count = 0
        while True:
            await asyncio.sleep(0.5)
            check_count += 1

            # Skip if no buffer or already processing
            if not audio_buffer or is_processing or len(audio_buffer) < MIN_AUDIO_LENGTH:
                continue

            # Check max buffer time
            if buffer_start_time:
                buffer_elapsed = asyncio.get_event_loop().time() - buffer_start_time
                if buffer_elapsed > MAX_BUFFER_SECONDS:
                    logger.info(f"Max buffer time exceeded ({buffer_elapsed:.1f}s), forcing processing")
                    await process_audio_buffer()

    timeout_task = asyncio.create_task(check_buffer_timeout())

    try:
        while True:
            message = await websocket.receive_text()
            data = json.loads(message)
            event_type = data.get("event")

            if event_type == "connected":
                logger.info(f"Media stream connected: {data}")

            elif event_type == "start":
                # Stream started - extract parameters
                stream_sid = data.get("streamSid")
                start_data = data.get("start", {})
                custom_params = start_data.get("customParameters", {})

                company_id = int(custom_params.get("company_id", 0))
                agent_id_str = custom_params.get("agent_id", "")
                agent_id = int(agent_id_str) if agent_id_str else None
                conversation_id = custom_params.get("conversation_id", "")

                # Get OpenAI API key for the company
                openai_cred = credential_service.get_credential_by_service_name(
                    db, "openai", company_id
                )
                if openai_cred:
                    openai_api_key = credential_service.get_decrypted_credential(
                        db, openai_cred.id, company_id
                    )

                if not openai_api_key:
                    logger.error(f"No OpenAI API key found for company {company_id}")

                # Update voice call with stream_sid
                await voice_service.handle_call_connected(call_sid, stream_sid)

                logger.info(f"Stream started: {stream_sid}, company: {company_id}, agent: {agent_id}")

                # Check if we should use OpenAI Realtime mode
                agent = None
                use_realtime = False
                if agent_id and settings.OPENAI_REALTIME_ENABLED:
                    agent = agent_service.get_agent(db, agent_id, company_id)
                    if agent and agent.llm_provider == "openai":
                        use_realtime = True
                        logger.info(f"Agent {agent_id} uses OpenAI, enabling Realtime mode")

                if use_realtime and openai_api_key:
                    # Switch to OpenAI Realtime mode
                    timeout_task.cancel()
                    try:
                        await timeout_task
                    except asyncio.CancelledError:
                        pass

                    realtime_success = await handle_realtime_mode(
                        websocket=websocket,
                        stream_sid=stream_sid,
                        agent=agent,
                        openai_api_key=openai_api_key,
                        voice_service=voice_service,
                        db=db,
                        conversation_id=conversation_id,
                        company_id=company_id,
                    )
                    if realtime_success:
                        # Realtime mode handled everything, exit
                        break
                    else:
                        # Fallback to standard mode - restart timeout task
                        logger.info("Falling back to standard VAD+STT+LLM+TTS mode")
                        timeout_task = asyncio.create_task(check_buffer_timeout())

            elif event_type == "media":
                # Incoming audio from caller
                media_data = data.get("media", {})
                payload = media_data.get("payload", "")

                if payload:
                    # Decode base64 mulaw audio
                    try:
                        audio_bytes = base64.b64decode(payload)

                        # Tap into full-call recording buffer
                        recording_buffer.extend(audio_bytes)

                        # Process through Silero VAD
                        vad_result = vad_service.process_mulaw(audio_bytes)

                        # Buffer audio while speech is active
                        if is_speech_active:
                            audio_buffer.extend(audio_bytes)

                        if vad_result:
                            if vad_result.event == VADEvent.SPEECH_START:
                                # Speech started - begin buffering
                                is_speech_active = True
                                audio_buffer.extend(audio_bytes)  # Add the chunk that triggered start
                                buffer_start_time = asyncio.get_event_loop().time()
                                logger.info(f"Silero VAD: Speech started (prob={vad_result.probability:.2f})")

                            elif vad_result.event == VADEvent.SPEECH_END:
                                # Speech ended - process the buffer
                                is_speech_active = False
                                logger.info(f"Silero VAD: Speech ended (prob={vad_result.probability:.2f}, duration={vad_result.speech_duration_ms:.0f}ms, buffer={len(audio_buffer)} bytes)")
                                if len(audio_buffer) >= MIN_AUDIO_LENGTH:
                                    await process_audio_buffer()
                                else:
                                    logger.warning(f"Buffer too small ({len(audio_buffer)} bytes), skipping STT")
                                    audio_buffer.clear()
                                    buffer_start_time = None

                            # SPEECH_CONTINUE and SILENCE - audio already buffered above if speech is active

                    except Exception as e:
                        logger.error(f"Error processing audio: {e}")

            elif event_type == "stop":
                logger.info(f"Stream stopped: {stream_sid}")
                if audio_buffer:
                    await process_audio_buffer()
                if recording_buffer:
                    pcm = mulaw_to_pcm16(bytes(recording_buffer))
                    upload_recording(db, call_sid, pcm, sample_rate=8000)
                break

            elif event_type == "mark":
                # Mark event - audio playback completed
                logger.debug(f"Mark event: {data.get('mark', {}).get('name')}")

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for call: {call_sid}")
        if recording_buffer:
            pcm = mulaw_to_pcm16(bytes(recording_buffer))
            upload_recording(db, call_sid, pcm, sample_rate=8000)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        if recording_buffer:
            pcm = mulaw_to_pcm16(bytes(recording_buffer))
            upload_recording(db, call_sid, pcm, sample_rate=8000)
    finally:
        timeout_task.cancel()
        try:
            await timeout_task
        except asyncio.CancelledError:
            pass

        # Reset VAD state
        vad_service.reset()

        # Save transcript before cleanup
        voice_service.save_transcript(call_sid)


# --- Phone Number Management Endpoints (Authenticated) ---

@router.get("/phone-numbers", response_model=list[TwilioPhoneNumberResponse])
async def list_phone_numbers(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List all Twilio phone numbers for the company."""
    phone_numbers = db.query(TwilioPhoneNumber).filter(
        TwilioPhoneNumber.company_id == current_user.company_id
    ).all()
    return phone_numbers


@router.post("/phone-numbers", response_model=TwilioPhoneNumberResponse)
async def create_phone_number(
    phone_number: TwilioPhoneNumberCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Add a new Twilio phone number configuration."""
    # Check if phone number already exists
    existing = db.query(TwilioPhoneNumber).filter(
        TwilioPhoneNumber.phone_number == phone_number.phone_number
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Phone number already configured")

    db_phone = TwilioPhoneNumber(
        phone_number=phone_number.phone_number,
        friendly_name=phone_number.friendly_name,
        company_id=current_user.company_id,
        default_agent_id=phone_number.default_agent_id,
        integration_id=phone_number.integration_id,
        welcome_message=phone_number.welcome_message,
        language=phone_number.language
    )
    db.add(db_phone)
    db.commit()
    db.refresh(db_phone)
    return db_phone


@router.put("/phone-numbers/{phone_id}", response_model=TwilioPhoneNumberResponse)
async def update_phone_number(
    phone_id: int,
    phone_update: TwilioPhoneNumberUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update a Twilio phone number configuration."""
    db_phone = db.query(TwilioPhoneNumber).filter(
        TwilioPhoneNumber.id == phone_id,
        TwilioPhoneNumber.company_id == current_user.company_id
    ).first()

    if not db_phone:
        raise HTTPException(status_code=404, detail="Phone number not found")

    update_data = phone_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_phone, key, value)

    db.commit()
    db.refresh(db_phone)
    return db_phone


@router.delete("/phone-numbers/{phone_id}")
async def delete_phone_number(
    phone_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete a Twilio phone number configuration."""
    db_phone = db.query(TwilioPhoneNumber).filter(
        TwilioPhoneNumber.id == phone_id,
        TwilioPhoneNumber.company_id == current_user.company_id
    ).first()

    if not db_phone:
        raise HTTPException(status_code=404, detail="Phone number not found")

    db.delete(db_phone)
    db.commit()
    return {"status": "deleted"}


@router.get("/phone-numbers/fetch-from-twilio/{integration_id}")
async def fetch_phone_numbers_from_twilio(
    integration_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Fetch available phone numbers from Twilio account.
    Returns a list of phone numbers that can be imported.
    """
    # Get the integration
    integration = db.query(Integration).filter(
        Integration.id == integration_id,
        Integration.company_id == current_user.company_id,
        Integration.type == "twilio_voice"
    ).first()

    if not integration:
        raise HTTPException(status_code=404, detail="Twilio integration not found")

    # Get credentials
    try:
        credentials = integration_service.get_decrypted_credentials(integration)
        account_sid = credentials.get("account_sid")
        auth_token = credentials.get("auth_token")

        if not account_sid or not auth_token:
            raise HTTPException(status_code=400, detail="Invalid Twilio credentials")

        # Fetch phone numbers from Twilio
        client = TwilioClient(account_sid, auth_token)
        incoming_numbers = client.incoming_phone_numbers.list()

        # Get already configured phone numbers
        configured_numbers = db.query(TwilioPhoneNumber.phone_number).filter(
            TwilioPhoneNumber.company_id == current_user.company_id
        ).all()
        configured_set = {n[0] for n in configured_numbers}

        # Format response
        twilio_numbers = []
        for number in incoming_numbers:
            # Capabilities can be a dict or object depending on Twilio SDK version
            caps = number.capabilities
            if hasattr(caps, 'voice'):
                voice_cap = caps.voice
                sms_cap = caps.sms
                mms_cap = caps.mms
            elif isinstance(caps, dict):
                voice_cap = caps.get("voice", False)
                sms_cap = caps.get("sms", False)
                mms_cap = caps.get("mms", False)
            else:
                voice_cap = sms_cap = mms_cap = False

            twilio_numbers.append({
                "phone_number": number.phone_number,
                "friendly_name": number.friendly_name,
                "capabilities": {
                    "voice": voice_cap,
                    "sms": sms_cap,
                    "mms": mms_cap,
                },
                "is_configured": number.phone_number in configured_set
            })

        return {
            "numbers": twilio_numbers,
            "total": len(twilio_numbers)
        }

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        logger.error(f"Error fetching Twilio phone numbers: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Failed to fetch phone numbers from Twilio: {str(e)}")


# --- Voice Call History Endpoints (Authenticated) ---

@router.get("/calls", response_model=VoiceCallListResponse)
async def list_voice_calls(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    contact_id: Optional[int] = None,
    conversation_id: Optional[str] = None,
    direction: Optional[str] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List voice calls for the company."""
    query = db.query(VoiceCall).filter(VoiceCall.company_id == current_user.company_id)
    if contact_id:
        query = query.filter(VoiceCall.contact_id == contact_id)
    if conversation_id:
        query = query.filter(VoiceCall.conversation_id == conversation_id)
    if direction:
        query = query.filter(VoiceCall.direction == direction)
    if status:
        query = query.filter(VoiceCall.status == status)
    total = query.count()
    calls = query.order_by(VoiceCall.started_at.desc()).offset(skip).limit(limit).all()
    return VoiceCallListResponse(
        calls=calls,
        total=total,
        skip=skip,
        limit=limit
    )


@router.get("/calls/{call_sid}", response_model=VoiceCallResponse)
async def get_voice_call(
    call_sid: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get a specific voice call by call SID."""
    call = db.query(VoiceCall).filter(
        VoiceCall.call_sid == call_sid,
        VoiceCall.company_id == current_user.company_id
    ).first()

    if not call:
        raise HTTPException(status_code=404, detail="Voice call not found")

    return call


# --- Outbound Calling (Browser SDK) ---

class OutboundCallRequest(BaseModel):
    to_number: str
    contact_id: Optional[int] = None


@router.get("/token")
async def get_access_token(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Generate a Twilio Access Token with VoiceGrant for the browser-based Twilio Client SDK.
    If no TwiML App SID is stored in credentials, one is auto-created via the Twilio API.
    """
    from twilio.jwt.access_token import AccessToken
    from twilio.jwt.access_token.grants import VoiceGrant

    integration = db.query(Integration).filter(
        Integration.company_id == current_user.company_id,
        Integration.type == "twilio_voice",
        Integration.is_active == True
    ).first()

    if not integration:
        raise HTTPException(status_code=404, detail="No active Twilio Voice integration found")

    credentials = integration_service.get_decrypted_credentials(integration)
    account_sid = credentials.get("account_sid")
    auth_token = credentials.get("auth_token")
    api_key_sid = credentials.get("api_key_sid")
    api_key_secret = credentials.get("api_key_secret")
    twiml_app_sid = credentials.get("twiml_app_sid")

    if not account_sid or not auth_token:
        raise HTTPException(status_code=400, detail="Twilio credentials are incomplete")

    # Auto-create TwiML App if not already stored
    if not twiml_app_sid:
        try:
            twilio_client = TwilioClient(account_sid, auth_token)
            public_host = getattr(settings, "PUBLIC_HOST", None) or getattr(settings, "FRONTEND_URL", "")
            voice_url = f"https://{public_host}/api/v1/twilio/webhook/twiml-app"
            app = twilio_client.applications.create(
                friendly_name="HeyGenAlly Outbound Calls",
                voice_url=voice_url,
                voice_method="POST"
            )
            twiml_app_sid = app.sid
            # Persist SID back into integration credentials
            from app.services.vault_service import vault_service
            import json as _json
            existing = dict(credentials)
            existing["twiml_app_sid"] = twiml_app_sid
            integration.credentials = vault_service.encrypt(_json.dumps(existing))
            db.commit()
            logger.info(f"Auto-created TwiML App: {twiml_app_sid}")
        except Exception as e:
            logger.error(f"Failed to auto-create TwiML App: {e}")
            raise HTTPException(status_code=500, detail="Failed to create TwiML Application")

    identity = f"agent_{current_user.id}"
    signing_key = api_key_sid or account_sid
    signing_secret = api_key_secret or auth_token

    try:
        token = AccessToken(account_sid, signing_key, signing_secret, identity=identity)
        voice_grant = VoiceGrant(outgoing_application_sid=twiml_app_sid, incoming_allow=True)
        token.add_grant(voice_grant)
        return {"token": token.to_jwt(), "identity": identity}
    except Exception as e:
        logger.error(f"Error generating Twilio Access Token: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate access token")


@router.post("/webhook/twiml-app")
async def twiml_app_voice(request: Request, db: Session = Depends(get_db)):
    """
    TwiML webhook for outbound calls initiated via the Twilio Client SDK.
    Twilio calls this URL when the browser device places a call.
    Returns TwiML instructing Twilio to dial the destination number.
    """
    form_data = await request.form()
    to_number = form_data.get("To", "")
    call_sid = form_data.get("CallSid", "")
    caller_identity = form_data.get("From", "")

    logger.info(f"TwiML app outbound: CallSid={call_sid}, To={to_number}, From={caller_identity}")

    if not to_number:
        twiml = '''<?xml version="1.0" encoding="UTF-8"?>
<Response><Say>No destination number provided.</Say><Hangup/></Response>'''
        return get_twiml_response(twiml)

    # Determine caller ID: use the company's configured Twilio number if possible
    # Extract agent user_id from identity (format: agent_{user_id})
    caller_id = to_number  # fallback
    try:
        if caller_identity.startswith("agent_"):
            agent_user_id = int(caller_identity.split("_")[1])
            user = db.query(User).filter(User.id == agent_user_id).first()
            if user:
                phone_config = db.query(TwilioPhoneNumber).filter(
                    TwilioPhoneNumber.company_id == user.company_id,
                    TwilioPhoneNumber.is_active == True
                ).first()
                if phone_config:
                    caller_id = phone_config.phone_number
    except Exception as e:
        logger.warning(f"Could not determine caller ID: {e}")

    # Get status callback URL for tracking call lifecycle
    public_host = getattr(settings, "PUBLIC_HOST", None) or ""
    if public_host:
        status_callback = f"https://{public_host}/api/v1/twilio/webhook/voice/status"
        twiml = f'''<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Dial callerId="{caller_id}">
    <Number statusCallbackEvent="initiated ringing answered completed"
            statusCallback="{status_callback}"
            statusCallbackMethod="POST">{to_number}</Number>
  </Dial>
</Response>'''
    else:
        twiml = f'''<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Dial callerId="{caller_id}">
    <Number>{to_number}</Number>
  </Dial>
</Response>'''

    return get_twiml_response(twiml)


@router.post("/outbound-call")
async def initiate_outbound_call(
    call_request: OutboundCallRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Register an outbound call initiated via the browser SDK.
    Creates (or re-uses) the conversation session and returns session info.
    The actual call is placed client-side via the Twilio JS SDK after this.
    """
    from app.services import conversation_session_service, contact_service

    company_id = current_user.company_id
    to_number = call_request.to_number.strip()

    if not to_number.startswith("+"):
        raise HTTPException(status_code=400, detail="Phone number must be in E.164 format (+1234567890)")

    phone_config = db.query(TwilioPhoneNumber).filter(
        TwilioPhoneNumber.company_id == company_id,
        TwilioPhoneNumber.is_active == True
    ).first()

    if not phone_config:
        raise HTTPException(status_code=400, detail="No active Twilio phone number configured for your company")

    # Resolve contact
    if call_request.contact_id:
        contact = db.query(Contact).filter(
            Contact.id == call_request.contact_id,
            Contact.company_id == company_id
        ).first()
        if not contact:
            raise HTTPException(status_code=404, detail="Contact not found")
    else:
        contact = contact_service.get_or_create_contact_for_channel(
            db, company_id=company_id, channel="twilio_voice",
            channel_identifier=to_number, name=to_number
        )

    # Create/reuse conversation session keyed by outbound number + agent
    conversation_id = f"twilio_outbound_{to_number}_{current_user.id}"
    session = conversation_session_service.get_or_create_session(
        db,
        conversation_id=conversation_id,
        workflow_id=None,
        contact_id=contact.id,
        channel="twilio_voice",
        company_id=company_id,
        agent_id=phone_config.default_agent_id
    )
    session.status = "active"
    session.is_client_connected = True
    session.context = {}
    db.commit()

    logger.info(f"Outbound call session ready: {conversation_id} -> {to_number}")

    return {
        "conversation_id": conversation_id,
        "session_id": str(session.id),
        "to_number": to_number,
        "from_number": phone_config.phone_number,
        "contact_id": contact.id,
        "contact_name": contact.name or to_number,
    }


# ── Call Transfer ──────────────────────────────────────────────────────────────

class TransferRequest(BaseModel):
    destination: str          # E.164 phone number or "client:agent_42"
    warm: bool = False        # True = warm (agent consults first), False = blind


class SuperviseRequest(BaseModel):
    mode: str = "listen"      # listen | barge | whisper


def _get_twilio_client_for_company(db: Session, company_id: int):
    """Return an authenticated TwilioClient + credentials dict for a company."""
    integration = db.query(Integration).filter(
        Integration.company_id == company_id,
        Integration.type == "twilio_voice",
        Integration.is_active == True,
    ).first()
    if not integration:
        raise HTTPException(status_code=404, detail="No active Twilio Voice integration")
    creds = integration_service.get_decrypted_credentials(integration)
    account_sid = creds.get("account_sid")
    auth_token = creds.get("auth_token")
    if not account_sid or not auth_token:
        raise HTTPException(status_code=400, detail="Twilio credentials incomplete")
    return TwilioClient(account_sid, auth_token), creds


@router.post("/calls/{call_sid}/transfer")
async def transfer_call(
    call_sid: str,
    body: TransferRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Blind or warm-transfer an active call to a phone number or Twilio Client identity.
    Blind: immediately redirect the caller.
    Warm: put the caller on hold, let the agent consult the destination, then bridge.
    """
    call = db.query(VoiceCall).filter(
        VoiceCall.call_sid == call_sid,
        VoiceCall.company_id == current_user.company_id,
    ).first()
    if not call:
        raise HTTPException(status_code=404, detail="Call not found")

    twilio_client, creds = _get_twilio_client_for_company(db, current_user.company_id)
    public_host = getattr(settings, "PUBLIC_HOST", None) or creds.get("public_host", "")

    destination = body.destination.strip()
    # Determine TwiML dial target
    if destination.startswith("client:"):
        client_name = destination[len("client:"):]
        dial_xml = f"<Client>{client_name}</Client>"
    else:
        dial_xml = f"<Number>{destination}</Number>"

    if body.warm:
        # Warm transfer: put caller on hold, return a conference TwiML so the
        # agent and destination can consult, then complete via /warm-transfer-complete
        conf_name = f"warm_{call_sid}"
        hold_twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say>Please hold while we connect you.</Say>
  <Enqueue workflowSid="{conf_name}">conference</Enqueue>
</Response>"""
        # Simpler: move caller into a named conference on hold
        hold_twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say>Please hold while we connect you.</Say>
  <Dial>
    <Conference startConferenceOnEnter="false" endConferenceOnExit="false"
                waitUrl="http://twimlets.com/holdmusic?Bucket=com.twilio.music.classical"
                beep="false">{conf_name}</Conference>
  </Dial>
</Response>"""
        twilio_client.calls(call_sid).update(twiml=hold_twiml)
        logger.info(f"[TRANSFER] Warm: put {call_sid} in conference {conf_name}")
        return {"status": "warm_hold", "conference": conf_name, "destination": destination}
    else:
        # Blind transfer: immediately redirect call to destination
        twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Dial>{dial_xml}</Dial>
</Response>"""
        twilio_client.calls(call_sid).update(twiml=twiml)

        # Update VoiceCall record
        from datetime import datetime as _dt
        call.status = "completed"
        call.ended_at = _dt.utcnow()
        db.commit()
        logger.info(f"[TRANSFER] Blind: redirected {call_sid} -> {destination}")
        return {"status": "transferred", "destination": destination}


@router.post("/calls/{call_sid}/warm-transfer-complete")
async def warm_transfer_complete(
    call_sid: str,
    body: TransferRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    After warm consultation, bridge the held caller with the destination and drop the agent.
    """
    call = db.query(VoiceCall).filter(
        VoiceCall.call_sid == call_sid,
        VoiceCall.company_id == current_user.company_id,
    ).first()
    if not call:
        raise HTTPException(status_code=404, detail="Call not found")

    twilio_client, _ = _get_twilio_client_for_company(db, current_user.company_id)
    conf_name = f"warm_{call_sid}"
    destination = body.destination.strip()

    if destination.startswith("client:"):
        dial_xml = f"<Client>{destination[len('client:'):]}</Client>"
    else:
        dial_xml = f"<Number>{destination}</Number>"

    # Move caller out of hold conference and dial destination directly
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Dial>{dial_xml}</Dial>
</Response>"""
    twilio_client.calls(call_sid).update(twiml=twiml)
    logger.info(f"[TRANSFER] Warm complete: {call_sid} -> {destination}")
    return {"status": "transferred", "destination": destination}


@router.post("/calls/{call_sid}/supervise")
async def supervise_call(
    call_sid: str,
    body: SuperviseRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Supervisor monitoring: put the original call into a conference and return TwiML
    for the supervisor's browser to join in listen / barge / whisper mode.

    Mode:
      listen  — supervisor hears everything, is muted, cannot be heard by anyone
      barge   — supervisor can speak to both caller and agent
      whisper — supervisor can speak to agent only (coaching), caller cannot hear
    """
    call = db.query(VoiceCall).filter(
        VoiceCall.call_sid == call_sid,
        VoiceCall.company_id == current_user.company_id,
    ).first()
    if not call:
        raise HTTPException(status_code=404, detail="Call not found")

    if body.mode not in ("listen", "barge", "whisper"):
        raise HTTPException(status_code=400, detail="mode must be listen, barge, or whisper")

    twilio_client, _ = _get_twilio_client_for_company(db, current_user.company_id)
    conf_name = f"supervise_{call_sid}"

    # Move the original call leg into a named conference
    caller_conf_twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Dial>
    <Conference startConferenceOnEnter="true" endConferenceOnExit="true"
                beep="false" record="false">{conf_name}</Conference>
  </Dial>
</Response>"""
    try:
        twilio_client.calls(call_sid).update(twiml=caller_conf_twiml)
    except Exception as e:
        logger.warning(f"[SUPERVISE] Could not redirect call {call_sid} to conference: {e}")

    # Supervisor join params vary by mode
    supervisor_muted = body.mode == "listen"
    coaching = body.mode == "whisper"
    # The call_sid_to_coach is the agent's call leg; for simplicity we coach the original SID
    coach_sid = call_sid if coaching else None

    supervisor_identity = f"agent_{current_user.id}"
    supervisor_conf_twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Dial>
    <Conference startConferenceOnEnter="true" endConferenceOnExit="false"
                muted="{str(supervisor_muted).lower()}" beep="false"
                {"coaching=\"true\" callSidToCoach=\"" + coach_sid + "\"" if coaching and coach_sid else ""}
                >{conf_name}</Conference>
  </Dial>
</Response>"""

    logger.info(f"[SUPERVISE] Supervisor {current_user.id} joining {conf_name} in {body.mode} mode")

    return {
        "status": "ok",
        "conference": conf_name,
        "mode": body.mode,
        "supervisor_twiml": supervisor_conf_twiml,
        "supervisor_identity": supervisor_identity,
    }


@router.post("/calls/queue/{entry_id}/accept-bridge")
async def accept_queue_bridge(
    entry_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    After accepting a queued voice call, bridge the caller's Twilio call to the
    accepting agent's browser (Twilio Client identity = agent_{user_id}).
    """
    from app.models.call_queue import CallQueueEntry
    from datetime import datetime as dt

    entry = db.query(CallQueueEntry).filter(
        CallQueueEntry.id == entry_id,
        CallQueueEntry.company_id == current_user.company_id,
    ).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Queue entry not found")

    twilio_client, _ = _get_twilio_client_for_company(db, current_user.company_id)
    agent_identity = f"agent_{current_user.id}"

    # Redirect the caller's call leg to dial the agent's Twilio Client
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say>Connecting you to an agent now.</Say>
  <Dial>
    <Client>{agent_identity}</Client>
  </Dial>
</Response>"""
    try:
        twilio_client.calls(entry.call_sid).update(twiml=twiml)
        entry.status = "connected"
        entry.connected_at = dt.utcnow()
        entry.assigned_agent_id = current_user.id
        db.commit()
        logger.info(f"[QUEUE BRIDGE] Call {entry.call_sid} bridged to {agent_identity}")
        return {"status": "connected", "agent_identity": agent_identity, "call_sid": entry.call_sid}
    except Exception as e:
        logger.error(f"[QUEUE BRIDGE] Failed to bridge {entry.call_sid}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to bridge call: {str(e)}")


# ── Multi-party Conference (Item 4) ───────────────────────────────────────────

class AddParticipantRequest(BaseModel):
    participant: str            # E.164 phone number or "client:agent_N"
    caller_id: Optional[str] = None  # Caller ID to use for outbound leg


@router.post("/calls/{call_sid}/add-participant")
async def add_participant(
    call_sid: str,
    body: AddParticipantRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Move original call into a named conference and dial a new participant in.
    If the call is already in a conference (detected by our naming convention) we reuse it.
    """
    call = db.query(VoiceCall).filter(
        VoiceCall.call_sid == call_sid,
        VoiceCall.company_id == current_user.company_id,
    ).first()
    if not call:
        raise HTTPException(status_code=404, detail="Call not found")

    twilio_client, creds = _get_twilio_client_for_company(db, current_user.company_id)
    conf_name = f"conf_{call_sid}"

    # Move the original call into the conference (idempotent — Twilio ignores if already there)
    original_conf_twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Dial>
    <Conference startConferenceOnEnter="true" endConferenceOnExit="false"
                beep="false" record="false">{conf_name}</Conference>
  </Dial>
</Response>"""
    try:
        twilio_client.calls(call_sid).update(twiml=original_conf_twiml)
    except Exception as e:
        logger.warning(f"[CONFERENCE] Could not redirect original call {call_sid} to conf: {e}")

    # Determine caller_id
    caller_id_to_use = body.caller_id
    if not caller_id_to_use:
        from app.models.twilio_phone_number import TwilioPhoneNumber
        phone_cfg = db.query(TwilioPhoneNumber).filter(
            TwilioPhoneNumber.company_id == current_user.company_id,
            TwilioPhoneNumber.is_active == True,
        ).first()
        caller_id_to_use = phone_cfg.phone_number if phone_cfg else creds.get("phone_number", "")

    participant = body.participant.strip()

    # Dial the new participant into the conference
    public_host = getattr(settings, "PUBLIC_HOST", None) or creds.get("public_host", "")
    status_cb = f"https://{public_host}/api/v1/twilio/webhook/voice/status" if public_host else None

    if participant.startswith("client:"):
        # Dial a Twilio Client (browser agent)
        client_identity = participant[len("client:"):]
        participant_twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Dial>
    <Conference startConferenceOnEnter="true" endConferenceOnExit="false"
                beep="true">{conf_name}</Conference>
  </Dial>
</Response>"""
        try:
            new_call = twilio_client.calls.create(
                twiml=participant_twiml,
                to=f"client:{client_identity}",
                from_=caller_id_to_use,
            )
            logger.info(f"[CONFERENCE] Added client {client_identity} to conf {conf_name}: {new_call.sid}")
            return {"status": "participant_added", "conference": conf_name, "participant_call_sid": new_call.sid}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to add participant: {e}")
    else:
        # Outbound PSTN call to the participant
        participant_twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Dial>
    <Conference startConferenceOnEnter="true" endConferenceOnExit="false"
                beep="true">{conf_name}</Conference>
  </Dial>
</Response>"""
        try:
            kwargs = {
                "twiml": participant_twiml,
                "to": participant,
                "from_": caller_id_to_use,
            }
            if status_cb:
                kwargs["status_callback"] = status_cb
                kwargs["status_callback_event"] = ["initiated", "ringing", "answered", "completed"]
            new_call = twilio_client.calls.create(**kwargs)
            logger.info(f"[CONFERENCE] Added PSTN {participant} to conf {conf_name}: {new_call.sid}")
            return {"status": "participant_added", "conference": conf_name, "participant_call_sid": new_call.sid}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to add participant: {e}")


# ── CSAT SMS webhook (Item 5) ─────────────────────────────────────────────────

@router.post("/webhook/csat-response")
async def handle_csat_response(request: Request, db: Session = Depends(get_db)):
    """
    Twilio SMS webhook. Receives CSAT replies (digits 1-5) from callers.
    Finds the most recent VoiceCall for that phone number and records the score.
    """
    from datetime import datetime as _dt
    form_data = await request.form()
    from_number = form_data.get("From", "")
    body_text = (form_data.get("Body") or "").strip()

    twiml_ok = '<?xml version="1.0" encoding="UTF-8"?><Response><Message>Thank you for your feedback!</Message></Response>'
    twiml_invalid = '<?xml version="1.0" encoding="UTF-8"?><Response><Message>Please reply with a number from 1 to 5.</Message></Response>'

    if not body_text.isdigit() or int(body_text) not in range(1, 6):
        return Response(content=twiml_invalid, media_type="application/xml")

    score = int(body_text)

    # Find the most recent call from this number with csat_sent_at set and no score yet
    call = (
        db.query(VoiceCall)
        .filter(
            VoiceCall.from_number == from_number,
            VoiceCall.csat_sent_at != None,
            VoiceCall.csat_score == None,
        )
        .order_by(VoiceCall.csat_sent_at.desc())
        .first()
    )

    if call:
        call.csat_score = score
        db.commit()
        logger.info(f"[CSAT] Recorded score {score} for call {call.call_sid} from {from_number}")

    return Response(content=twiml_ok, media_type="application/xml")
