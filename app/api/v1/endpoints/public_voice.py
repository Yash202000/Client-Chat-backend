
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, Query
from sqlalchemy.orm import Session
from app.services import chat_service, workflow_service, agent_execution_service, messaging_service, integration_service, company_service, agent_service, contact_service, conversation_session_service, credential_service
from app.services.workflow_execution_service import WorkflowExecutionService
from app.schemas import chat_message as schemas_chat_message
import json
from typing import List, Dict, Any
from app.core.dependencies import get_current_user_from_ws, get_db
from app.models import user as models_user, conversation_session as models_conversation_session
from app.core.websockets import manager
from app.services.stt_service import STTService, GroqSTTService
from app.services.tts_service import TTSService
from fastapi import UploadFile
import io
import logging
from types import SimpleNamespace

router = APIRouter()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

import asyncio

@router.websocket("/public/voice/{company_id}/{agent_id}/{session_id}")
async def public_voice_websocket_endpoint(
    websocket: WebSocket,
    company_id: int,
    agent_id: int,
    session_id: str,
    user_type: str = Query(...),
    voice_id: str = Query("21m00Tcm4TlvDq8ikWAM"), # Default voice
    db: Session = Depends(get_db)
):
    logger.info(f"New public voice connection for session {session_id}")
    # Fetch agent details to get the configured voice
    agent = agent_service.get_agent(db, agent_id, company_id)
    if not agent:
        logger.error(f"Agent not found for agent_id: {agent_id}, company_id: {company_id}")
        await websocket.close(code=1008)
        return
        
    logger.info(f"Agent found: {agent.name}")
    logger.info(f"Agent credential object: {agent.credential}")

    final_voice_id = voice_id
    tts_provider = 'voice_engine' # Default provider
    stt_provider = 'deepgram' # Default provider
    if agent:
        if agent.voice_id:
            final_voice_id = agent.voice_id
        if agent.tts_provider:
            tts_provider = agent.tts_provider
        if agent.stt_provider:
            stt_provider = agent.stt_provider
    
    logger.info(f"STT Provider: {stt_provider}, TTS Provider: {tts_provider}, Voice ID: {final_voice_id}")

    await manager.connect(websocket, session_id, user_type)
    logger.info(f"WebSocket connected to manager for session {session_id}")
    
    stt_service = None
    if stt_provider == "groq":
        groq_api_key = None
        # Check if the agent has a specific credential for Groq
        if agent.credential and agent.credential.service == 'groq':
            logger.info("Found Groq credential associated with the agent.")
            try:
                # The credential service returns the raw decrypted key for simple services like Groq
                decrypted_key = credential_service.get_decrypted_credential(db, agent.credential.id, company_id)
                if decrypted_key and isinstance(decrypted_key, str):
                    groq_api_key = decrypted_key
                    logger.info("Using Groq API key from Vault.")
                else:
                    logger.warning("Groq credential found but the decrypted key is not a valid string.")
            except Exception as e:
                logger.error(f"Failed to decrypt Groq credential: {e}")
        
        if not groq_api_key:
            logger.warning("Groq API key not found in agent's vault. Falling back to environment variable.")

        stt_service = GroqSTTService(api_key=groq_api_key)

    elif stt_provider == "deepgram":
        stt_service = STTService(websocket)
    else:
        logger.error(f"Unsupported STT provider: {stt_provider}")
        await websocket.close(code=1008)
        return

    tts_service = TTSService()
    logger.info("STT and TTS services initialized")
    
    transcript_queue = asyncio.Queue()
    audio_buffer = bytearray()
    last_audio_time = None

    async def handle_transcription():
        logger.info("Starting transcription handler")
        if stt_provider == "deepgram":
            if await stt_service.connect():
                while True:
                    try:
                        message = await stt_service.deepgram_ws.receive_json()
                        if message.get("type") == "Results":
                            transcript = message["channel"]["alternatives"][0]["transcript"]
                            if transcript and message.get("is_final", False):
                                await transcript_queue.put(transcript)
                    except Exception as e:
                        logger.error(f"Error receiving from STT service: {e}")
                        break
            await stt_service.close()
        logger.info("Transcription handler finished")
        # Groq does not use a persistent connection for transcription

    async def handle_audio_from_client():
        nonlocal audio_buffer, last_audio_time
        logger.info("Starting audio from client handler")
        try:
            while True:
                audio_chunk = await websocket.receive_bytes()
                last_audio_time = asyncio.get_event_loop().time()
                if stt_provider == "deepgram":
                    if stt_service.deepgram_ws and not stt_service.deepgram_ws.closed:
                        await stt_service.deepgram_ws.send_bytes(audio_chunk)
                    else:
                        break
                elif stt_provider == "groq":
                    audio_buffer.extend(audio_chunk)

        except WebSocketDisconnect:
            logger.info("Client disconnected from audio stream")
        except Exception as e:
            logger.error(f"Error receiving audio from client: {e}")
        logger.info("Audio from client handler finished")

    async def process_groq_buffer():
        nonlocal audio_buffer, last_audio_time
        logger.info("Starting Groq buffer processor")
        while True:
            await asyncio.sleep(0.5) # Check every 500ms
            if audio_buffer and last_audio_time and (asyncio.get_event_loop().time() - last_audio_time > 1.0): # 1 second pause
                logger.info("Pause detected, processing audio buffer")
                try:
                    # Create a duck-typed object that mimics UploadFile for the STT service
                    async def read_audio_data():
                        return bytes(audio_buffer)

                    mock_audio_file = SimpleNamespace(
                        filename="audio.wav",
                        content_type="audio/wav",
                        read=read_audio_data
                    )
                    
                    transcript_result = await stt_service.transcribe(mock_audio_file)
                    transcript = transcript_result.get("text")
                    if transcript:
                        logger.info(f"STT transcription result: {transcript}")
                        await transcript_queue.put(transcript)
                except Exception as e:
                    logger.error(f"Error during Groq transcription: {e}")
                finally:
                    audio_buffer.clear()
                    last_audio_time = None
        logger.info("Groq buffer processor finished")


    transcription_task = asyncio.create_task(handle_transcription())
    client_audio_task = asyncio.create_task(handle_audio_from_client())
    
    groq_buffer_task = None
    if stt_provider == "groq":
        groq_buffer_task = asyncio.create_task(process_groq_buffer())

    logger.info("All tasks created")

    try:
        while True:
            transcript = await transcript_queue.get()
            logger.info(f"Processing transcript: {transcript}")
            
            if transcript:
                # 1. Save and broadcast the user's transcribed message
                user_message = schemas_chat_message.ChatMessageCreate(message=transcript, message_type='message')
                db_user_message = chat_service.create_chat_message(db, user_message, agent_id, session_id, company_id, "user")
                await manager.broadcast_to_session(session_id, schemas_chat_message.ChatMessage.from_orm(db_user_message).json(), "user")

                # 2. Generate the agent's response
                agent_response_text = await agent_execution_service.generate_agent_response(
                    db, agent_id, session_id, company_id, transcript
                )
                logger.info(f"LLM response: {agent_response_text}")

                # 3. Save and broadcast the agent's text message
                agent_message = schemas_chat_message.ChatMessageCreate(message=agent_response_text, message_type='message')
                db_agent_message = chat_service.create_chat_message(db, agent_message, agent_id, session_id, company_id, "agent")
                await manager.broadcast_to_session(session_id, schemas_chat_message.ChatMessage.from_orm(db_agent_message).json(), "agent")

                # 4. Convert the agent's response to speech and stream it
                audio_stream = tts_service.text_to_speech_stream(agent_response_text, final_voice_id, tts_provider)
                logger.info("Streaming TTS audio to client...")
                async for audio_chunk in audio_stream:
                    await websocket.send_bytes(audio_chunk)
                
                transcript_queue.task_done()
            logger.info("Finished processing transcript")

    except WebSocketDisconnect:
        logger.info(f"Client in voice session #{session_id} disconnected")
    except Exception as e:
        logger.error(f"Error in main voice processing loop: {e}")
    finally:
        logger.info("Cleaning up tasks and resources")
        transcription_task.cancel()
        client_audio_task.cancel()
        if groq_buffer_task:
            groq_buffer_task.cancel()
        await tts_service.close()
        manager.disconnect(websocket, session_id)
        logger.info(f"Cleaned up resources for voice session #{session_id}")
