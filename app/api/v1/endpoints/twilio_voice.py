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
from app.services import credential_service, integration_service
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

# Configuration
SILENCE_THRESHOLD = float(getattr(settings, 'TWILIO_VOICE_SILENCE_THRESHOLD', 0.6))  # seconds of silence to trigger processing
MIN_AUDIO_LENGTH = 3200  # Minimum audio buffer size (~0.4 seconds at 8kHz)
MAX_BUFFER_SECONDS = 8  # Maximum seconds to buffer before forcing processing (prevents endless buffering)
# VAD thresholds with hysteresis to prevent rapid toggling
VAD_SPEECH_START_THRESHOLD = 55  # Energy level to start detecting speech (higher = more certain it's speech)
VAD_SPEECH_END_THRESHOLD = 40    # Energy level to stop detecting speech (lower = more certain it's silence)


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
    last_speech_time = None  # Last time we detected actual speech (not just audio packets)
    buffer_start_time = None  # When we started buffering (to enforce max buffer time)
    is_processing = False
    is_speaking = False  # Track if user is currently speaking

    def calculate_audio_energy(audio_bytes: bytes) -> float:
        """Calculate RMS energy of mulaw audio to detect voice activity."""
        if not audio_bytes:
            return 0
        # Mulaw audio is 8-bit, center is at 127
        # Calculate deviation from center (which indicates sound amplitude)
        total = sum(abs(b - 127) for b in audio_bytes)
        return total / len(audio_bytes)

    async def process_audio_buffer():
        """Process accumulated audio through STT and get AI response."""
        nonlocal audio_buffer, is_processing, buffer_start_time

        if not audio_buffer or is_processing or len(audio_buffer) < MIN_AUDIO_LENGTH:
            return

        is_processing = True
        buffer_start_time = None  # Reset buffer timer
        try:
            # Convert accumulated mulaw to PCM for Whisper
            pcm_16k = audio_converter.buffer_to_whisper_format(audio_buffer)

            # Transcribe with Whisper
            stt_service = OpenAISTTService(api_key=openai_api_key)
            result = await stt_service.transcribe_pcm(pcm_16k)

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

    async def check_silence():
        """Background task to detect end of speech using VAD."""
        nonlocal last_speech_time, is_speaking, buffer_start_time
        check_count = 0
        while True:
            await asyncio.sleep(0.1)
            check_count += 1
            current_time = asyncio.get_event_loop().time()

            # Skip if no buffer or already processing
            if not audio_buffer or is_processing or len(audio_buffer) < MIN_AUDIO_LENGTH:
                continue

            # Calculate times
            silence_elapsed = current_time - last_speech_time if last_speech_time else 0
            buffer_elapsed = current_time - buffer_start_time if buffer_start_time else 0

            # Log every 10 checks (1 second)
            if check_count % 10 == 0:
                logger.info(f"VAD: buffer={len(audio_buffer)} bytes ({buffer_elapsed:.1f}s), silence={silence_elapsed:.2f}s, speaking={is_speaking}")

            # Process if: (silence detected AND not speaking) OR (max buffer time exceeded)
            should_process = False
            reason = ""

            if not is_speaking and silence_elapsed > SILENCE_THRESHOLD:
                should_process = True
                reason = f"silence detected ({silence_elapsed:.2f}s)"
            elif buffer_elapsed > MAX_BUFFER_SECONDS:
                should_process = True
                reason = f"max buffer time exceeded ({buffer_elapsed:.1f}s)"

            if should_process:
                logger.info(f"Processing audio: {reason}, buffer={len(audio_buffer)} bytes")
                await process_audio_buffer()

    silence_task = asyncio.create_task(check_silence())

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

            elif event_type == "media":
                # Incoming audio from caller
                media_data = data.get("media", {})
                payload = media_data.get("payload", "")

                if payload:
                    # Decode base64 mulaw audio and add to buffer
                    try:
                        audio_bytes = base64.b64decode(payload)

                        # Calculate audio energy for VAD
                        energy = calculate_audio_energy(audio_bytes)

                        # Use hysteresis for speech detection to prevent rapid toggling
                        # Higher threshold to START speaking, lower threshold to STOP
                        if is_speaking:
                            # Currently speaking - need energy to drop below lower threshold to stop
                            if energy < VAD_SPEECH_END_THRESHOLD:
                                is_speaking = False
                                logger.info(f"Speech ended (energy: {energy:.1f}, buffer: {len(audio_buffer)} bytes)")
                            else:
                                # Still speaking - add to buffer
                                audio_buffer.extend(audio_bytes)
                                last_speech_time = asyncio.get_event_loop().time()
                        else:
                            # Not speaking - need energy above higher threshold to start
                            if energy > VAD_SPEECH_START_THRESHOLD:
                                is_speaking = True
                                audio_buffer.extend(audio_bytes)
                                current_time = asyncio.get_event_loop().time()
                                last_speech_time = current_time
                                # Start buffer timer if this is first speech
                                if buffer_start_time is None:
                                    buffer_start_time = current_time
                                logger.info(f"Speech started (energy: {energy:.1f})")

                        # Log first audio packet
                        if len(audio_buffer) == len(audio_bytes):
                            logger.info(f"First audio packet: {len(audio_bytes)} bytes, energy: {energy:.1f}")
                    except Exception as e:
                        logger.error(f"Error decoding audio: {e}")

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
        silence_task.cancel()
        try:
            await silence_task
        except asyncio.CancelledError:
            pass

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
