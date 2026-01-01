"""
FreeSWITCH Voice API endpoints for handling incoming calls and audio streams.

FreeSWITCH connects via WebSocket using mod_audio_stream module.
Configure your dialplan to connect to: ws://your-server/api/v1/freeswitch/audio-stream
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
from app.models.freeswitch_phone_number import FreeSwitchPhoneNumber
from app.models.voice_call import VoiceCall
from app.services.freeswitch_voice_service import FreeSwitchVoiceService, get_freeswitch_phone_numbers_by_company
from app.services.audio_conversion_service import AudioConversionService
from app.services.stt_service import OpenAISTTService
from app.services.tts_service import OpenAITTSService
from app.services.vad_service import SileroVADService, VADEvent, VADResult
from app.services.openai_realtime_service import (
    OpenAIRealtimeService,
    convert_l16_8k_to_pcm_24k,
    convert_pcm_24k_to_l16_8k,
)
from app.services import credential_service, agent_service, chat_service
from app.services.agent_execution_service import _get_tools_for_agent
from app.services.tool_execution_service import execute_tool
from app.services.connection_manager import manager
from app.schemas.chat_message import ChatMessageCreate
from app.schemas.freeswitch_voice import (
    FreeSwitchPhoneNumberCreate,
    FreeSwitchPhoneNumberUpdate,
    FreeSwitchPhoneNumberResponse,
    FreeSwitchPhoneNumberListResponse,
)

router = APIRouter()
logger = logging.getLogger(__name__)

# Configuration - Silero VAD settings (matching LiveKit defaults)
VAD_THRESHOLD = float(getattr(settings, 'VAD_THRESHOLD', 0.5))  # Speech probability threshold
VAD_MIN_SPEECH_MS = int(getattr(settings, 'VAD_MIN_SPEECH_MS', 50))  # Minimum speech duration (ms) - LiveKit: 0.05s
VAD_MIN_SILENCE_MS = int(getattr(settings, 'VAD_MIN_SILENCE_MS', 550))  # Minimum silence to end speech (ms) - LiveKit: 0.55s
MIN_AUDIO_LENGTH = 3200  # Minimum audio buffer size (~0.2 seconds at 8kHz, 16-bit)
MAX_BUFFER_SECONDS = 8  # Maximum seconds to buffer before forcing processing


# --- OpenAI Realtime Mode Handler ---

async def handle_freeswitch_realtime_mode(
    websocket: WebSocket,
    call_uuid: str,
    agent,
    openai_api_key: str,
    voice_service: FreeSwitchVoiceService,
    db: Session,
    conversation_id: str,
    company_id: int,
    sample_rate: int = 8000,
):
    """
    Handle FreeSWITCH call using OpenAI Realtime API for ultra-low latency.
    """
    logger.info(f"Starting OpenAI Realtime mode for FreeSWITCH call {call_uuid}")
    agent_id = agent.id if agent else None

    # Get agent tools for function calling
    tools = []
    try:
        tool_definitions = await _get_tools_for_agent(agent)
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

    if not await realtime.connect():
        logger.error("Failed to connect to OpenAI Realtime API")
        return False

    transcripts = []

    async def forward_freeswitch_to_openai():
        """Forward audio from FreeSWITCH to OpenAI Realtime API."""
        try:
            while True:
                message = await websocket.receive_text()
                data = json.loads(message)
                event_type = data.get("event")

                if event_type == "audio":
                    audio_data = data.get("audio", "")
                    if audio_data:
                        l16_bytes = base64.b64decode(audio_data)
                        pcm_24k = convert_l16_8k_to_pcm_24k(l16_bytes)
                        await realtime.send_audio(pcm_24k)

                elif event_type == "disconnect":
                    logger.info(f"FreeSWITCH disconnect: {data.get('hangup_cause')}")
                    break

        except WebSocketDisconnect:
            logger.info("FreeSWITCH WebSocket disconnected")
        except Exception as e:
            logger.error(f"Error forwarding FreeSWITCH to OpenAI: {e}")

    async def forward_openai_to_freeswitch():
        """Forward audio from OpenAI Realtime API to FreeSWITCH."""
        try:
            async for event in realtime.receive_events():
                audio_bytes = realtime.extract_audio_delta(event)
                if audio_bytes:
                    l16_bytes = convert_pcm_24k_to_l16_8k(audio_bytes)
                    l16_b64 = base64.b64encode(l16_bytes).decode("utf-8")
                    await websocket.send_json({"event": "audio", "audio": l16_b64})

                func_call = realtime.extract_function_call(event)
                if func_call:
                    logger.info(f"Realtime function call: {func_call.name}")
                    try:
                        import json as json_module
                        args = json_module.loads(func_call.arguments)
                        result = await execute_tool(
                            db=db,
                            tool_name=func_call.name,
                            parameters=args,
                            session_id=call_uuid or "",
                            company_id=agent.company_id if agent else 0,
                        )
                        result_str = json_module.dumps(result) if isinstance(result, dict) else str(result)
                        await realtime.submit_function_result(func_call.call_id, result_str)
                    except Exception as e:
                        logger.error(f"Error executing function: {e}")
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

                if event.type == "error":
                    logger.error(f"Realtime API error: {event.data}")

        except Exception as e:
            logger.error(f"Error forwarding OpenAI to FreeSWITCH: {e}")

    try:
        await asyncio.gather(
            forward_freeswitch_to_openai(),
            forward_openai_to_freeswitch(),
        )
    finally:
        await realtime.disconnect()
        logger.info(f"Realtime mode ended for {call_uuid}")

    return True


# --- Audio Stream WebSocket ---

@router.websocket("/audio-stream")
async def freeswitch_audio_stream(
    websocket: WebSocket,
    db: Session = Depends(get_db)
):
    """
    WebSocket endpoint for FreeSWITCH mod_audio_stream.

    FreeSWITCH connects here and sends audio in L16 (16-bit PCM) format.

    Message format from FreeSWITCH:
    - connect: {"event": "connect", "uuid": "...", "caller_id_number": "...", "destination_number": "..."}
    - audio: {"event": "audio", "uuid": "...", "audio": "base64_encoded_l16"}
    - disconnect: {"event": "disconnect", "uuid": "...", "hangup_cause": "..."}

    Message format to FreeSWITCH:
    - audio: {"event": "audio", "audio": "base64_encoded_l16"}
    - hangup: {"event": "hangup"}
    """
    await websocket.accept()
    logger.info("FreeSWITCH audio stream WebSocket connected")

    # Send initial handshake acknowledgment - mod_audio_stream expects this before sending connect event
    await websocket.send_json({"event": "connected", "protocol": "audio_stream", "version": "1.0"})

    voice_service = FreeSwitchVoiceService(db)
    audio_converter = AudioConversionService()

    # State variables
    openai_api_key = None
    call_uuid = None
    company_id = None
    agent_id = None
    sample_rate = 8000

    # Audio buffering for VAD (Voice Activity Detection)
    audio_buffer = bytearray()
    buffer_start_time = None
    is_processing = False
    is_speech_active = False  # Track if we're currently in a speech segment

    # Initialize Silero VAD (will be re-initialized with correct sample rate after connect)
    vad_service = SileroVADService(
        threshold=VAD_THRESHOLD,
        min_speech_duration_ms=VAD_MIN_SPEECH_MS,
        min_silence_duration_ms=VAD_MIN_SILENCE_MS,
        sample_rate=8000,  # Default, will be updated on connect
    )
    logger.info("Silero VAD initialized for FreeSWITCH connection")

    async def process_audio_buffer():
        """Process accumulated audio through STT and get AI response."""
        nonlocal audio_buffer, is_processing

        if not audio_buffer or is_processing or len(audio_buffer) < MIN_AUDIO_LENGTH:
            return

        is_processing = True
        try:
            # Convert accumulated L16 PCM to format for Whisper
            pcm_16k = audio_converter.freeswitch_buffer_to_whisper_format(audio_buffer, sample_rate)

            # Transcribe with Whisper
            stt_service = OpenAISTTService(api_key=openai_api_key)
            result = await stt_service.transcribe_pcm(pcm_16k)

            transcribed_text = result.get("text", "").strip()

            if transcribed_text:
                logger.info(f"Transcribed: {transcribed_text}")

                # Get AI response
                response_text = await voice_service.process_speech(
                    call_uuid=call_uuid,
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
        """Generate TTS and stream back to FreeSWITCH."""
        try:
            tts_service = OpenAITTSService(api_key=openai_api_key)

            # Get PCM audio from TTS
            pcm_audio = await tts_service.text_to_speech_pcm(text)

            # Convert to FreeSWITCH format (L16 at configured sample rate)
            l16_b64 = audio_converter.tts_to_freeswitch(
                pcm_audio,
                tts_sample_rate=24000,
                target_sample_rate=sample_rate
            )

            # Send to FreeSWITCH in chunks
            chunks = audio_converter.chunk_audio_for_freeswitch(l16_b64, chunk_size=640)

            for chunk in chunks:
                audio_message = {
                    "event": "audio",
                    "audio": chunk
                }
                await websocket.send_json(audio_message)
                await asyncio.sleep(0.02)  # 20ms between chunks

        except Exception as e:
            logger.error(f"Error streaming TTS: {e}")

    async def check_buffer_timeout():
        """Background task to enforce max buffer time."""
        nonlocal buffer_start_time
        while True:
            await asyncio.sleep(0.5)

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

            if event_type == "connect":
                # Call connected - extract parameters
                call_uuid = data.get("uuid")
                caller_id_number = data.get("caller_id_number", "")
                caller_id_name = data.get("caller_id_name", "")
                destination_number = data.get("destination_number", "")
                channel_data = data.get("channel_data", {})

                logger.info(f"FreeSWITCH call connected: {call_uuid} from {caller_id_number} to {destination_number}")

                # Handle incoming call
                call_config = await voice_service.handle_incoming_call(
                    call_uuid=call_uuid,
                    from_number=caller_id_number,
                    to_number=destination_number,
                    caller_name=caller_id_name,
                    channel_data=channel_data
                )

                if "error" in call_config:
                    logger.error(f"Call config error: {call_config['error']}")
                    # Send hangup
                    await websocket.send_json({"event": "hangup", "cause": "UNALLOCATED_NUMBER"})
                    continue

                company_id = call_config["company_id"]
                agent_id = call_config.get("agent_id")
                conversation_id = call_config.get("conversation_id", "")
                sample_rate = call_config.get("sample_rate", 8000)

                # Reinitialize VAD with correct sample rate if different
                if sample_rate != 8000:
                    vad_service = SileroVADService(
                        threshold=VAD_THRESHOLD,
                        min_speech_duration_ms=VAD_MIN_SPEECH_MS,
                        min_silence_duration_ms=VAD_MIN_SILENCE_MS,
                        sample_rate=sample_rate,
                    )
                    logger.info(f"Reinitialized VAD with sample rate: {sample_rate}")

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

                # Mark call as connected
                await voice_service.handle_call_connected(call_uuid)

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

                    realtime_success = await handle_freeswitch_realtime_mode(
                        websocket=websocket,
                        call_uuid=call_uuid,
                        agent=agent,
                        openai_api_key=openai_api_key,
                        voice_service=voice_service,
                        db=db,
                        conversation_id=conversation_id,
                        company_id=company_id,
                        sample_rate=sample_rate,
                    )
                    if realtime_success:
                        break
                    else:
                        logger.info("Falling back to standard VAD+STT+LLM+TTS mode")
                        timeout_task = asyncio.create_task(check_buffer_timeout())

                # Send welcome message if configured (only in standard mode)
                welcome_message = call_config.get("welcome_message")
                if welcome_message and openai_api_key and not use_realtime:
                    await stream_tts_response(welcome_message)

                logger.info(f"Call setup complete: {call_uuid}, company: {company_id}, agent: {agent_id}")

            elif event_type == "audio":
                # Incoming audio from caller (L16 PCM)
                audio_data = data.get("audio", "")

                if audio_data:
                    try:
                        audio_bytes = base64.b64decode(audio_data)

                        # Process through Silero VAD
                        vad_result = vad_service.process_l16(audio_bytes)

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

            elif event_type == "disconnect":
                hangup_cause = data.get("hangup_cause", "NORMAL_CLEARING")
                logger.info(f"FreeSWITCH call disconnected: {call_uuid}, cause: {hangup_cause}")

                # Process any remaining audio
                if audio_buffer:
                    await process_audio_buffer()

                # Handle call ended
                if call_uuid:
                    await voice_service.handle_call_ended(call_uuid, hangup_cause)
                break

    except WebSocketDisconnect:
        logger.info(f"FreeSWITCH WebSocket disconnected: {call_uuid}")
        if call_uuid:
            await voice_service.handle_call_ended(call_uuid, "WEBSOCKET_DISCONNECT")
    except Exception as e:
        logger.error(f"FreeSWITCH WebSocket error: {e}")
        if call_uuid:
            await voice_service.handle_call_ended(call_uuid, "ERROR")
    finally:
        timeout_task.cancel()
        try:
            await timeout_task
        except asyncio.CancelledError:
            pass

        # Reset VAD state
        vad_service.reset()


# --- Phone Number Management Endpoints (Authenticated) ---

@router.get("/phone-numbers", response_model=FreeSwitchPhoneNumberListResponse)
async def list_phone_numbers(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List FreeSWITCH phone numbers for the company."""
    phone_numbers = get_freeswitch_phone_numbers_by_company(
        db, current_user.company_id, skip, limit
    )
    total = db.query(FreeSwitchPhoneNumber).filter(
        FreeSwitchPhoneNumber.company_id == current_user.company_id
    ).count()
    return FreeSwitchPhoneNumberListResponse(
        phone_numbers=phone_numbers,
        total=total
    )


@router.post("/phone-numbers", response_model=FreeSwitchPhoneNumberResponse)
async def create_phone_number(
    phone_number: FreeSwitchPhoneNumberCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new FreeSWITCH phone number configuration."""
    # Check if number already exists
    existing = db.query(FreeSwitchPhoneNumber).filter(
        FreeSwitchPhoneNumber.phone_number == phone_number.phone_number
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Phone number already configured")

    db_phone = FreeSwitchPhoneNumber(
        **phone_number.model_dump(),
        company_id=current_user.company_id
    )
    db.add(db_phone)
    db.commit()
    db.refresh(db_phone)
    return db_phone


@router.get("/phone-numbers/{phone_id}", response_model=FreeSwitchPhoneNumberResponse)
async def get_phone_number(
    phone_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get a specific FreeSWITCH phone number configuration."""
    db_phone = db.query(FreeSwitchPhoneNumber).filter(
        FreeSwitchPhoneNumber.id == phone_id,
        FreeSwitchPhoneNumber.company_id == current_user.company_id
    ).first()

    if not db_phone:
        raise HTTPException(status_code=404, detail="Phone number not found")

    return db_phone


@router.put("/phone-numbers/{phone_id}", response_model=FreeSwitchPhoneNumberResponse)
async def update_phone_number(
    phone_id: int,
    phone_update: FreeSwitchPhoneNumberUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update a FreeSWITCH phone number configuration."""
    db_phone = db.query(FreeSwitchPhoneNumber).filter(
        FreeSwitchPhoneNumber.id == phone_id,
        FreeSwitchPhoneNumber.company_id == current_user.company_id
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
    """Delete a FreeSWITCH phone number configuration."""
    db_phone = db.query(FreeSwitchPhoneNumber).filter(
        FreeSwitchPhoneNumber.id == phone_id,
        FreeSwitchPhoneNumber.company_id == current_user.company_id
    ).first()

    if not db_phone:
        raise HTTPException(status_code=404, detail="Phone number not found")

    db.delete(db_phone)
    db.commit()
    return {"status": "deleted"}


# --- FreeSWITCH Dialplan Helper ---

@router.get("/dialplan-example")
async def get_dialplan_example(
    current_user: User = Depends(get_current_user)
):
    """
    Returns an example FreeSWITCH dialplan configuration for connecting to this server.
    """
    # Get the public host from settings or use a placeholder
    public_host = getattr(settings, 'PUBLIC_HOST', 'your-server.com')
    ws_url = f"wss://{public_host}/api/v1/freeswitch/audio-stream"

    example = f"""
<!-- FreeSWITCH Dialplan Example for AI Agent Integration -->
<!-- Add this to your dialplan (e.g., /etc/freeswitch/dialplan/default.xml) -->

<extension name="ai_agent">
  <condition field="destination_number" expression="^(\\d+)$">
    <action application="answer"/>
    <action application="sleep" data="500"/>
    <!-- Connect to AgentConnect WebSocket -->
    <action application="audio_stream" data="{ws_url} start both"/>
  </condition>
</extension>

<!--
Notes:
1. Make sure mod_audio_stream is loaded (modules.conf.xml)
2. The WebSocket URL should use wss:// for production
3. Audio format is L16 (16-bit signed PCM, little-endian)
4. Default sample rate is 8000 Hz, can be configured in mod_audio_stream
5. Configure your extensions/DIDs in the AgentConnect Voice settings
-->
"""
    return {"dialplan": example, "websocket_url": ws_url}
