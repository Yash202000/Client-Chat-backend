from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, Query
from sqlalchemy.orm import Session
from app.services import chat_service, workflow_service, agent_execution_service, messaging_service, integration_service, company_service, agent_service, contact_service, conversation_session_service, user_service, workflow_trigger_service
from app.services.workflow_execution_service import WorkflowExecutionService
from app.schemas import chat_message as schemas_chat_message, websocket as schemas_websocket
from app.schemas.websockets import WebSocketMessage
import json
from typing import List, Dict, Any
from app.core.dependencies import get_current_user_from_ws, get_db
from app.models import user as models_user, conversation_session as models_conversation_session
from app.models.workflow_trigger import TriggerChannel
from app.services.connection_manager import manager
from app.services.stt_service import STTService, GroqSTTService
from app.services.tts_service import TTSService
from fastapi import UploadFile
import io
import asyncio
import datetime

router = APIRouter()

# (router definition)


@router.websocket("/wschat/{channel_id}")
async def internal_chat_websocket_endpoint(
    websocket: WebSocket,
    channel_id: int,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_user_from_ws)
):
    print(f"Attempting to connect to WebSocket for channel {channel_id}")
    channel_id_str = str(channel_id)

    await manager.connect(websocket, channel_id_str,"user")
    user_service.update_user_presence(db, user_id=current_user.id, status="online")
    presence_message = WebSocketMessage(type="presence_update", payload={"user_id": current_user.id, "status": "online"})
    await manager.broadcast(presence_message.model_dump_json(), channel_id_str)

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket, channel_id_str)
        user_service.update_user_presence(db, user_id=current_user.id, status="offline")
        presence_message = WebSocketMessage(type="presence_update", payload={"user_id": current_user.id, "status": "offline"})
        await manager.broadcast(presence_message.model_dump_json(), channel_id_str)

@router.websocket("/voice/{company_id}/{agent_id}/{session_id}")
async def voice_websocket_endpoint(
    websocket: WebSocket,
    company_id: int,
    agent_id: int,
    session_id: str,
    user_type: str = Query(...),
    voice_id: str = Query("21m00Tcm4TlvDq8ikWAM"), # Default voice
    db: Session = Depends(get_db)
):
    # Fetch agent details to get the configured voice
    agent = agent_service.get_agent(db, agent_id, company_id)
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

    await manager.connect(websocket, session_id, user_type)
    
    stt_service = None
    if stt_provider == "deepgram":
        stt_service = STTService(websocket)
    else:
        stt_service = GroqSTTService()

    tts_service = TTSService()
    
    transcript_queue = asyncio.Queue()
    audio_buffer = bytearray()
    last_audio_time = None

    async def handle_transcription():
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
                        print(f"Error receiving from STT service: {e}")
                        break
            await stt_service.close()
        # Groq does not use a persistent connection for transcription

    async def handle_audio_from_client():
        nonlocal audio_buffer, last_audio_time
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
            pass
        except Exception as e:
            print(f"Error receiving audio from client: {e}")

    async def process_groq_buffer():
        nonlocal audio_buffer, last_audio_time
        while True:
            await asyncio.sleep(0.5) # Check every 500ms
            if audio_buffer and last_audio_time and (asyncio.get_event_loop().time() - last_audio_time > 1.0): # 1 second pause
                try:
                    # Create an UploadFile-like object from the buffer
                    audio_file = UploadFile(filename="audio.wav", file=io.BytesIO(audio_buffer), content_type="audio/wav")
                    transcript_result = await stt_service.transcribe(audio_file)
                    transcript = transcript_result.get("text")
                    if transcript:
                        await transcript_queue.put(transcript)
                except Exception as e:
                    print(f"Error during Groq transcription: {e}")
                finally:
                    audio_buffer.clear()
                    last_audio_time = None


    transcription_task = asyncio.create_task(handle_transcription())
    client_audio_task = asyncio.create_task(handle_audio_from_client())
    
    groq_buffer_task = None
    if stt_provider == "groq":
        groq_buffer_task = asyncio.create_task(process_groq_buffer())


    try:
        while True:
            transcript = await transcript_queue.get()
            
            if transcript:
                # 1. Save and broadcast the user's transcribed message
                user_message = schemas_chat_message.ChatMessageCreate(message=transcript, message_type='message')
                db_user_message = chat_service.create_chat_message(db, user_message, agent_id, session_id, company_id, "user")
                await manager.broadcast_to_session(session_id, schemas_chat_message.ChatMessage.model_validate(db_user_message).model_dump_json(), "user")

                # 2. Generate the agent's response
                agent_response_text = await agent_execution_service.generate_agent_response(
                    db, agent_id, session_id, company_id, transcript
                )

                # 3. Save and broadcast the agent's text message
                agent_message = schemas_chat_message.ChatMessageCreate(message=agent_response_text, message_type='message')
                db_agent_message = chat_service.create_chat_message(db, agent_message, agent_id, session_id, company_id, "agent")
                await manager.broadcast_to_session(session_id, schemas_chat_message.ChatMessage.model_validate(db_agent_message).model_dump_json(), "agent")

                # 4. Convert the agent's response to speech and stream it
                audio_stream = tts_service.text_to_speech_stream(agent_response_text, final_voice_id, tts_provider)
                async for audio_chunk in audio_stream:
                    await websocket.send_bytes(audio_chunk)
                
                transcript_queue.task_done()

    except WebSocketDisconnect:
        print(f"Client in voice session #{session_id} disconnected")
    except Exception as e:
        print(f"Error in main voice processing loop: {e}")
    finally:
        transcription_task.cancel()
        client_audio_task.cancel()
        if groq_buffer_task:
            groq_buffer_task.cancel()
        await tts_service.close()
        manager.disconnect(websocket, session_id)
        print(f"Cleaned up resources for voice session #{session_id}")



@router.websocket("/internal/voice/{agent_id}/{session_id}")
async def internal_voice_websocket_endpoint(
    websocket: WebSocket,
    agent_id: int,
    session_id: str,
    user_type: str = Query(...),
    voice_id: str = Query("default_voice_id"),
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_user_from_ws)
):
    company_id = current_user.company_id
    agent = agent_service.get_agent(db, agent_id, company_id)
    stt_provider = 'deepgram' # Default provider
    if agent and agent.stt_provider:
        stt_provider = agent.stt_provider
    await manager.connect(websocket, session_id, user_type)
    
    stt_service = None
    if stt_provider == "deepgram":
        stt_service = STTService(websocket)
    else:
        stt_service = GroqSTTService()

    tts_service = TTSService()
    
    transcript_queue = asyncio.Queue()
    audio_buffer = bytearray()
    last_audio_time = None

    async def handle_transcription():
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
                        print(f"Error receiving from STT service: {e}")
                        break
            await stt_service.close()
        # Groq does not use a persistent connection for transcription

    async def handle_audio_from_client():
        nonlocal audio_buffer, last_audio_time
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
            pass
        except Exception as e:
            print(f"Error receiving audio from client: {e}")

    async def process_groq_buffer():
        nonlocal audio_buffer, last_audio_time
        while True:
            await asyncio.sleep(0.5) # Check every 500ms
            if audio_buffer and last_audio_time and (asyncio.get_event_loop().time() - last_audio_time > 1.0): # 1 second pause
                try:
                    # Create an UploadFile-like object from the buffer
                    audio_file = UploadFile(filename="audio.wav", file=io.BytesIO(audio_buffer), content_type="audio/wav")
                    transcript_result = await stt_service.transcribe(audio_file)
                    transcript = transcript_result.get("text")
                    if transcript:
                        await transcript_queue.put(transcript)
                except Exception as e:
                    print(f"Error during Groq transcription: {e}")
                finally:
                    audio_buffer.clear()
                    last_audio_time = None

    transcription_task = asyncio.create_task(handle_transcription())
    client_audio_task = asyncio.create_task(handle_audio_from_client())

    groq_buffer_task = None
    if stt_provider == "groq":
        groq_buffer_task = asyncio.create_task(process_groq_buffer())

    try:
        while True:
            transcript = await transcript_queue.get()
            
            if transcript:
                # When an agent speaks, we treat it as a message from the agent
                # and send it to the user.
                # For now, we'll just log it and send it back as text.
                # A full implementation would route this to the correct user.
                chat_message = schemas_chat_message.ChatMessageCreate(message=transcript, message_type='message')
                db_message = chat_service.create_chat_message(db, chat_message, agent_id, session_id, company_id, "agent")
                await manager.broadcast_to_session(session_id, schemas_chat_message.ChatMessage.model_validate(db_message).model_dump_json(), "agent")

                transcript_queue.task_done()

    except WebSocketDisconnect:
        print(f"Agent in voice session #{session_id} disconnected")
    except Exception as e:
        print(f"Error in internal voice processing loop: {e}")
    finally:
        transcription_task.cancel()
        client_audio_task.cancel()
        if groq_buffer_task:
            groq_buffer_task.cancel()
        await tts_service.close()
        manager.disconnect(websocket, session_id)
        print(f"Cleaned up resources for internal voice session #{session_id}")




@router.websocket("/{agent_id}/{session_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    agent_id: int,
    session_id: str,
    user_type: str = Query(...), # 'user' or 'agent'
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_user_from_ws)
):
    company_id = current_user.company_id # Get company_id from authenticated user
    print(f"[websocket_conversations] Attempting WebSocket connection for session: {session_id}, user: {current_user.email}, company_id: {company_id}")

    await manager.connect(websocket, session_id, user_type)
    print(f"[websocket_conversations] WebSocket connection established for session: {session_id}")

    # Update session status to active when user connects
    if user_type == "user":
        await conversation_session_service.update_session_connection_status(db, session_id, is_connected=True)

    # Instantiate the execution service
    workflow_exec_service = WorkflowExecutionService(db)
    
    try:
        while True:
            data = await websocket.receive_text()
            print(f"[websocket_conversations] Received data from frontend: {data}")
            if not data:
                continue
            
            try:
                message_data = json.loads(data)
                user_message = message_data.get('message')
                sender = message_data.get('sender')
            except (json.JSONDecodeError, AttributeError):
                print(f"[websocket_conversations] Received invalid data from session #{session_id}: {data}")
                continue

            if not user_message or not sender:
                print(f"[websocket_conversations] Missing user_message or sender: user_message={user_message}, sender={sender}")
                continue

            # 1. Log user message
            chat_message = schemas_chat_message.ChatMessageCreate(
                message=user_message,
                message_type=message_data.get('message_type', 'message'),
                token=message_data.get('token')
            )
            db_message = chat_service.create_chat_message(db, chat_message, agent_id, session_id, company_id, sender)
            print(f"[websocket_conversations] Created chat message: {db_message.id}")
            await manager.broadcast_to_session(session_id, schemas_chat_message.ChatMessage.model_validate(db_message).model_dump_json(), sender)
            print(f"[websocket_conversations] Broadcasted message to session: {session_id}")

            # If agent sends message, check session channel and send to external platform
            if sender == 'agent':
                session_obj = db.query(models_conversation_session.ConversationSession).filter(
                    models_conversation_session.ConversationSession.conversation_id == session_id,
                    models_conversation_session.ConversationSession.company_id == company_id
                ).first()
                
                if session_obj and session_obj.channel == 'whatsapp':
                    # Retrieve WhatsApp credentials for the company
                    # This part needs to be implemented based on your credential management
                    # For now, let's assume you have a way to get api_token and phone_number_id
                    # from your settings or integration service.
                    # Placeholder for actual credential retrieval
                    whatsapp_integration = integration_service.get_integration_by_type_and_company(db, "whatsapp", company_id)

                    if whatsapp_integration:
                        try:
                            # Decrypt credentials to get api_token and phone_number_id
                            whatsapp_credentials = integration_service.get_decrypted_credentials(whatsapp_integration)
                            api_token = whatsapp_credentials.get("api_token")
                            phone_number_id = whatsapp_credentials.get("phone_number_id")

                            if not api_token or not phone_number_id:
                                print(f"[websocket_conversations] WhatsApp credentials missing for company {company_id}")
                                return

                            await messaging_service.send_whatsapp_message(
                                recipient_phone_number=session_obj.contact.phone_number,
                                message_text=user_message,
                                integration=whatsapp_integration
                            )
                            print(f"[websocket_conversations] Sent message to WhatsApp for session {session_id}")
                        except Exception as e:
                            print(f"[websocket_conversations] Error sending to WhatsApp: {e}")

            # 2. If the message is from the user, execute the workflow
            if sender == 'user':
                # Try trigger-based workflow finding first (new system)
                workflow = workflow_trigger_service.find_workflow_for_channel_message(
                    db=db,
                    channel=TriggerChannel.WEBSOCKET,
                    company_id=company_id,
                    message=user_message,
                    session_data={"session_id": session_id, "agent_id": agent_id}
                )

                # Fallback to old similarity search if no trigger-based workflow found
                if not workflow:
                    workflow = workflow_service.find_similar_workflow(
                        db,
                        company_id=company_id,
                        query=user_message
                    )

                if not workflow:
                    # If no specific workflow matches, provide a generic response
                    print(f"[websocket_conversations] No specific workflow found for message: '{user_message}'")
                    agent_response_text = await agent_execution_service.generate_agent_response(
                        db, agent_id, session_id, company_id, message_data['message']
                    )
                    agent_message = schemas_chat_message.ChatMessageCreate(message=agent_response_text, message_type="message")
                    db_agent_message = chat_service.create_chat_message(db, agent_message, agent_id, session_id, company_id, "agent")
                    await manager.broadcast_to_session(session_id, schemas_chat_message.ChatMessage.model_validate(db_agent_message).model_dump_json(), "agent")
                    print(f"[websocket_conversations] Broadcasted agent response to session: {session_id}")
                    continue

                # 3. Execute the matched workflow with the current state (conversation_id)
                execution_result = await workflow_exec_service.execute_workflow(
                    user_message=user_message,
                    conversation_id=session_id,
                    company_id=company_id,
                    workflow=workflow
                )

                # 4. Handle the execution result
                if execution_result.get("status") == "completed":
                    agent_response_text = execution_result.get("response", "Workflow finished.")
                    agent_message = schemas_chat_message.ChatMessageCreate(message=agent_response_text, message_type="message")
                    db_agent_message = chat_service.create_chat_message(db, agent_message, agent_id, session_id, company_id, "agent")
                    await manager.broadcast_to_session(session_id, schemas_chat_message.ChatMessage.model_validate(db_agent_message).model_dump_json(), "agent")
                    print(f"[websocket_conversations] Broadcasted workflow completion to session: {session_id}")
                
                elif execution_result.get("status") == "paused_for_prompt":
                    # The workflow is paused and wants to prompt the user.
                    # We construct a special message to send to the frontend.
                    prompt_data = execution_result.get("prompt", {})
                    prompt_message = {
                        "message": prompt_data.get("text"),
                        "message_type": "prompt", # A custom type for the frontend to recognize
                        "options": prompt_data.get("options", []),
                        "sender": "agent",
                        "session_id": session_id,
                        "agent_id": agent_id,
                        "company_id": company_id,
                    }
                    # This message is not saved to the database, it's a transient prompt
                    await manager.broadcast_to_session(session_id, json.dumps(prompt_message), "agent")
                    print(f"[websocket_conversations] Broadcasted prompt to session: {session_id}")

                elif execution_result.get("status") == "paused_for_form":
                    form_data = execution_result.get("form", {})
                    form_message = {
                        "message": form_data.get("title"),
                        "message_type": "form",
                        "fields": form_data.get("fields", []),
                        "sender": "agent",
                        "session_id": session_id,
                        "agent_id": agent_id,
                        "company_id": company_id,
                    }
                    await manager.broadcast_to_session(session_id, json.dumps(form_message), "agent")
                    print(f"[websocket_conversations] Broadcasted form to session: {session_id}")

                # If the status is "paused_for_input", we do nothing and just wait for the next user message.

    except WebSocketDisconnect:
        manager.disconnect(websocket, session_id)
        print(f"Client in session #{session_id} disconnected")

        # Update session status to inactive when user disconnects
        # Only if there are no more user connections
        if user_type == "user" and not manager.has_user_connection(session_id):
            await conversation_session_service.update_session_connection_status(db, session_id, is_connected=False)


@router.websocket("/public/{company_id}/{agent_id}/{session_id}")
async def public_websocket_endpoint(
    websocket: WebSocket,
    company_id: int,
    agent_id: int,
    session_id: str,
    user_type: str = Query(...),  # 'user' or 'agent'
    db: Session = Depends(get_db)
):
    agent = agent_service.get_agent(db, agent_id, company_id)
    if not agent:
        await websocket.close(code=1008)
        return

    await manager.connect(websocket, session_id, user_type)

    # Update session status to active when user connects
    if user_type == "user":
        await conversation_session_service.update_session_connection_status(db, session_id, is_connected=True)

    workflow_exec_service = WorkflowExecutionService(db)

    try:
        while True:
            data = await websocket.receive_text()
            message_data = json.loads(data)
            user_message = message_data.get('message')
            sender = message_data.get('sender')

            if not user_message or not sender:
                continue

            # Ensure contact and session exist before creating a message
            contact = contact_service.get_or_create_contact_for_channel(db, company_id=company_id, channel="web_chat", channel_identifier=session_id)

            # Check if this is a new session
            existing_session = db.query(models_conversation_session.ConversationSession).filter(
                models_conversation_session.ConversationSession.conversation_id == session_id,
                models_conversation_session.ConversationSession.company_id == company_id
            ).first()
            is_new_session = existing_session is None

            session = conversation_session_service.get_or_create_session(db, conversation_id=session_id, workflow_id=None, contact_id=contact.id, channel="web_chat", company_id=company_id, agent_id=agent_id)

            # Broadcast new session creation to all company users
            if is_new_session:
                print(f"[websocket_conversations] 🆕 New session created: {session_id}. Broadcasting to company {company_id}")
                session_update_schema = schemas_websocket.WebSocketSessionUpdate.model_validate(session)
                await manager.broadcast_to_company(
                    company_id,
                    json.dumps({"type": "new_session", "session": session_update_schema.model_dump(by_alias=True)})
                )
                print(f"[websocket_conversations] ✅ Broadcasted new session to company {company_id}")

            # Handle form data: convert dict to JSON string for storage
            message_for_storage = user_message
            if isinstance(user_message, dict):
                # If it's form data, convert to JSON string for chat message storage
                message_for_storage = json.dumps(user_message)

            # Now, create and broadcast the chat message
            chat_message = schemas_chat_message.ChatMessageCreate(message=message_for_storage, message_type=message_data.get('message_type', 'message'))
            db_message = chat_service.create_chat_message(db, chat_message, agent_id, session_id, company_id, sender)
            await manager.broadcast_to_session(str(session_id), schemas_chat_message.ChatMessage.model_validate(db_message).model_dump_json(), sender)

            if sender == 'user':
                # The session is already guaranteed to exist, so we can proceed
                print(f"DEBUG [Websocket Loop]: Checking session status. ID: {session.id}, Status: '{session.status}', Workflow ID: {session.workflow_id}")

                execution_result = None
                if session.status == 'paused' and session.workflow_id:
                    # A workflow is already in progress, so we resume it.
                    workflow = workflow_service.get_workflow(db, session.workflow_id, company_id)
                    if workflow:
                         execution_result = await workflow_exec_service.execute_workflow(
                            user_message=message_for_storage, company_id=company_id, workflow=workflow, conversation_id=session_id
                        )
                else:
                    # No workflow is in progress, so we find a new one.
                    workflow = workflow_service.find_similar_workflow(db, company_id=company_id, query=message_for_storage)
                    if workflow:
                        execution_result = await workflow_exec_service.execute_workflow(
                            user_message=message_for_storage, company_id=company_id, workflow=workflow, conversation_id=session_id
                        )

                # If no workflow was found or resumed, fallback to the default agent response
                if not execution_result:
                    await agent_execution_service.generate_agent_response(db, agent_id, session.id, session_id, company_id, message_for_storage)
                    continue
                
                # Handle execution result
                if execution_result.get("status") == "completed":
                    agent_response_text = execution_result.get("response", "Workflow finished.")
                    agent_message = schemas_chat_message.ChatMessageCreate(message=agent_response_text, message_type="message")
                    db_agent_message = chat_service.create_chat_message(db, agent_message, agent_id, session_id, company_id, "agent")
                    await manager.broadcast_to_session(str(session_id), schemas_chat_message.ChatMessage.model_validate(db_agent_message).model_dump_json(), "agent")
                
                elif execution_result.get("status") == "paused_for_prompt":
                    prompt_data = execution_result.get("prompt", {})
                    prompt_message = {
                        "message": prompt_data.get("text"),
                        "message_type": "prompt",
                        "options": prompt_data.get("options", []),
                        "sender": "agent",
                    }
                    await manager.broadcast_to_session(str(session_id), json.dumps(prompt_message), "agent")

                elif execution_result.get("status") == "paused_for_form":
                    form_data = execution_result.get("form", {})
                    form_message = {
                        "message": form_data.get("title"),
                        "message_type": "form",
                        "fields": form_data.get("fields", []),
                        "sender": "agent",
                    }
                    await manager.broadcast_to_session(str(session_id), json.dumps(form_message), "agent")

    except WebSocketDisconnect:
        manager.disconnect(websocket, session_id)
        print(f"Client in session #{session_id} disconnected")

        # Update session status to inactive when user disconnects
        # Only if there are no more user connections
        if user_type == "user" and not manager.has_user_connection(session_id):
            await conversation_session_service.update_session_connection_status(db, session_id, is_connected=False)

