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

from app.core.dependencies import get_db, get_current_user
from app.core.config import settings
from app.models.user import User
from app.models.twilio_phone_number import TwilioPhoneNumber
from app.models.voice_call import VoiceCall
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
from app.services import credential_service, integration_service, agent_service, chat_service
from app.services.agent_execution_service import _get_tools_for_agent
from app.services.tool_execution_service import execute_tool
from app.services.connection_manager import manager
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
    form_data = await request.form()

    call_sid = form_data.get("CallSid")
    call_status = form_data.get("CallStatus")

    logger.info(f"Call status update: {call_sid} -> {call_status}")

    voice_service = TwilioVoiceService(db)

    if call_status in ["completed", "failed", "busy", "no-answer", "canceled"]:
        voice_service.save_transcript(call_sid)
        await voice_service.handle_call_ended(call_sid)

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
        try:
            async for event in realtime.receive_events():
                # Handle audio output
                audio_bytes = realtime.extract_audio_delta(event)
                if audio_bytes:
                    # Convert PCM 24kHz to mulaw 8kHz
                    mulaw_bytes = convert_pcm_24k_to_mulaw_8k(audio_bytes)
                    mulaw_b64 = base64.b64encode(mulaw_bytes).decode("utf-8")

                    media_message = {
                        "event": "media",
                        "streamSid": stream_sid,
                        "media": {"payload": mulaw_b64}
                    }
                    await websocket.send_json(media_message)

                # Handle function calls
                func_call = realtime.extract_function_call(event)
                if func_call:
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

                    # Save message to database
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
    buffer_start_time = None  # When we started buffering (to enforce max buffer time)
    is_processing = False
    is_speech_active = False  # Track if we're currently in a speech segment

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
                # Process any remaining audio
                if audio_buffer:
                    await process_audio_buffer()
                break

            elif event_type == "mark":
                # Mark event - audio playback completed
                logger.debug(f"Mark event: {data.get('mark', {}).get('name')}")

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for call: {call_sid}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
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
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List voice calls for the company."""
    calls = get_voice_calls_by_company(db, current_user.company_id, skip, limit)
    total = db.query(VoiceCall).filter(
        VoiceCall.company_id == current_user.company_id
    ).count()
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
