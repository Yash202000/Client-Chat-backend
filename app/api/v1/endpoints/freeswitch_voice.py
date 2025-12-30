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
from app.services import credential_service
from app.schemas.freeswitch_voice import (
    FreeSwitchPhoneNumberCreate,
    FreeSwitchPhoneNumberUpdate,
    FreeSwitchPhoneNumberResponse,
    FreeSwitchPhoneNumberListResponse,
)

router = APIRouter()
logger = logging.getLogger(__name__)

# Configuration
SILENCE_THRESHOLD = float(getattr(settings, 'FREESWITCH_SILENCE_THRESHOLD', 0.8))  # seconds
MIN_AUDIO_LENGTH = 3200  # Minimum audio buffer size (~0.2 seconds at 8kHz, 16-bit)


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
    last_audio_time = None
    is_processing = False

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

    async def check_silence():
        """Background task to detect end of speech."""
        nonlocal last_audio_time
        while True:
            await asyncio.sleep(0.1)
            if last_audio_time and audio_buffer:
                elapsed = asyncio.get_event_loop().time() - last_audio_time
                if elapsed > SILENCE_THRESHOLD and not is_processing:
                    await process_audio_buffer()

    silence_task = asyncio.create_task(check_silence())

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
                sample_rate = call_config.get("sample_rate", 8000)

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

                # Send welcome message if configured
                welcome_message = call_config.get("welcome_message")
                if welcome_message and openai_api_key:
                    await stream_tts_response(welcome_message)

                logger.info(f"Call setup complete: {call_uuid}, company: {company_id}, agent: {agent_id}")

            elif event_type == "audio":
                # Incoming audio from caller
                audio_data = data.get("audio", "")

                if audio_data:
                    try:
                        audio_bytes = base64.b64decode(audio_data)
                        audio_buffer.extend(audio_bytes)
                        last_audio_time = asyncio.get_event_loop().time()
                    except Exception as e:
                        logger.error(f"Error decoding audio: {e}")

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
        silence_task.cancel()


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
