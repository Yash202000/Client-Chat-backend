from fastapi import APIRouter, Request, Depends, HTTPException, Response
from sqlalchemy.orm import Session
import os
import logging
import traceback
import json
import base64

from app.core.dependencies import get_db
from app.api.v1.endpoints.websocket_conversations import process_attachments_for_storage
from app.core.config import settings
from app.services import (
    contact_service,
    conversation_session_service,
    chat_service,
    workflow_service,
    workflow_trigger_service,
    integration_service,
    messaging_service,
    agent_service,
    agent_execution_service
)
from app.services.workflow_execution_service import WorkflowExecutionService
from app.models.workflow_trigger import TriggerChannel
from app.services.connection_manager import manager
from app.schemas.chat_message import ChatMessageCreate
from app.schemas import websocket as schemas_websocket, chat_message as schemas_chat_message
from app.api.v1.endpoints.websocket_conversations import manager as session_ws_manager

router = APIRouter()

VERIFY_TOKEN = settings.WHATSAPP_VERIFY_TOKEN

@router.get("")
async def verify_webhook(request: Request):
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        print("Webhook verified successfully!")
        return Response(content=challenge, status_code=200)
    else:
        print("Webhook verification failed.")
        raise HTTPException(status_code=403, detail="Invalid verification token")

@router.post("")
async def receive_message(request: Request, db: Session = Depends(get_db)):
    data = await request.json()
    print(f"Received webhook data: {data}")

    try:
        if "entry" in data and data["entry"]:
            change = data["entry"][0]["changes"][0]
            if change.get("field") == "messages" and "messages" in change.get("value", {}):
                metadata = change["value"]["metadata"]
                message_data = change["value"]["messages"][0]
                
                phone_number_id = metadata["phone_number_id"]
                sender_phone = message_data["from"]
                
                message_text = ""
                message_type = message_data.get("type")
                attachments = []  # List to hold any media attachments
                pending_media = None  # Will be set if this is a media message

                if message_type == "text":
                    message_text = message_data["text"]["body"]
                elif message_type == "interactive":
                    interactive_type = message_data["interactive"]["type"]
                    if interactive_type == "button_reply":
                        # Use id (contains the key/value) instead of title (display text)
                        message_text = message_data["interactive"]["button_reply"]["id"]
                    elif interactive_type == "list_reply":
                        # Use id (contains the key/value) instead of title (display text)
                        message_text = message_data["interactive"]["list_reply"]["id"]
                    else:
                        print(f"Ignoring unknown interactive type: {interactive_type}")
                        return Response(status_code=200)
                elif message_type in ["image", "document", "audio", "video"]:
                    # Handle media messages
                    media_data = message_data.get(message_type, {})
                    media_id = media_data.get("id")

                    if not media_id:
                        print(f"No media ID found for {message_type} message")
                        return Response(status_code=200)

                    # Get caption if available (images/videos can have captions)
                    message_text = media_data.get("caption", "")

                    # We need the integration to download media, but we get it later
                    # Store media info for processing after we get the integration
                    pending_media = {
                        "media_id": media_id,
                        "media_type": message_type,
                        "mime_type": media_data.get("mime_type", "application/octet-stream"),
                        "filename": media_data.get("filename")  # Only documents have filename
                    }
                elif message_type == "location":
                    # Handle location messages
                    location_data = message_data.get("location", {})
                    latitude = location_data.get("latitude")
                    longitude = location_data.get("longitude")

                    if latitude is None or longitude is None:
                        print(f"Invalid location data received")
                        return Response(status_code=200)

                    # Create location attachment (same format as websocket)
                    attachments.append({
                        "location": {
                            "latitude": latitude,
                            "longitude": longitude,
                            "name": location_data.get("name"),
                            "address": location_data.get("address")
                        }
                    })
                    message_text = f"📍 Location ({latitude:.4f}, {longitude:.4f})"
                    print(f"[WhatsApp] Received location: {latitude}, {longitude}")
                else:
                    print(f"Ignoring unsupported message type: {message_type}")
                    return Response(status_code=200)

                integration = integration_service.get_integration_by_phone_number_id(db, phone_number_id=phone_number_id)
                if not integration:
                    print(f"Error: No active integration found for phone_number_id: {phone_number_id}")
                    return Response(status_code=200)

                company_id = integration.company_id

                # Save original user input (caption/text) before attachment processing
                # This prevents auto-generated filenames from triggering restart detection
                original_user_input = message_text

                # Download and process media if this is a media message
                if pending_media:
                    try:
                        print(f"[WhatsApp] Downloading {pending_media['media_type']} media: {pending_media['media_id']}")
                        media_result = await messaging_service.download_whatsapp_media(
                            media_id=pending_media["media_id"],
                            integration=integration,
                            db=db
                        )

                        # Create attachment dict in the format expected by process_attachments_for_storage
                        file_data_base64 = base64.b64encode(media_result["data"]).decode('utf-8')
                        attachment = {
                            "file_data": file_data_base64,
                            "file_name": pending_media.get("filename") or media_result["file_name"],
                            "file_type": media_result["mime_type"],
                            "file_size": len(media_result["data"])
                        }
                        attachments.append(attachment)

                        # Process attachments to upload to S3
                        attachment_text = process_attachments_for_storage(attachments)
                        print(f"[WhatsApp] Processed attachment: {attachment_text}")

                        # If no caption was provided, use attachment text as message
                        if not message_text:
                            message_text = attachment_text

                    except Exception as e:
                        print(f"[WhatsApp] Error downloading media: {e}")
                        # Continue processing without attachment if download fails
                        if not message_text:
                            message_text = f"[Media attachment - {pending_media['media_type']}]"

                contact = contact_service.get_or_create_contact_for_channel(
                    db, 
                    company_id=company_id, 
                    channel='whatsapp', 
                    channel_identifier=sender_phone,
                    name=change.get("value", {}).get("contacts", [{}])[0].get("profile", {}).get("name")
                )

                session = conversation_session_service.get_or_create_session(
                    db, conversation_id=sender_phone, workflow_id=None, contact_id=contact.id, channel='whatsapp', company_id=company_id
                )

                # Reopen resolved sessions when a new message arrives
                if session.status == 'resolved':
                    session = await conversation_session_service.reopen_resolved_session(db, session, company_id)
                    print(f"Reopened resolved session {session.conversation_id} for incoming WhatsApp message")

                # Check for restart command ("0", "restart", "start over", "cancel", "reset")
                # Only check on original user input, not auto-generated attachment filenames
                if original_user_input and conversation_session_service.is_restart_command(original_user_input):
                    print(f"[WhatsApp] Restart command received from {sender_phone}")

                    # Reset workflow state
                    was_reset = await conversation_session_service.reset_session_workflow(db, session, company_id)

                    # Save user's restart message to chat history
                    user_chat_message = ChatMessageCreate(message=message_text, message_type="text")
                    user_db_message = chat_service.create_chat_message(db, user_chat_message, agent_id=None, session_id=session.conversation_id, company_id=company_id, sender="user")

                    await session_ws_manager.broadcast_to_session(
                        session.conversation_id,
                        schemas_chat_message.ChatMessage.from_orm(user_db_message).json(),
                        "user"
                    )

                    # Send confirmation message
                    confirmation = "Conversation restarted. How can I help you?"
                    await messaging_service.send_whatsapp_message(
                        recipient_phone_number=sender_phone,
                        message_text=confirmation,
                        integration=integration,
                        db=db
                    )

                    # Save confirmation to chat history
                    agent_chat_message = ChatMessageCreate(message=confirmation, message_type="text")
                    agent_db_message = chat_service.create_chat_message(db, agent_chat_message, agent_id=None, session_id=session.conversation_id, company_id=company_id, sender="agent")

                    await session_ws_manager.broadcast_to_session(
                        session.conversation_id,
                        schemas_chat_message.ChatMessage.from_orm(agent_db_message).json(),
                        "agent"
                    )

                    return Response(status_code=200)

                chat_message = ChatMessageCreate(message=message_text, message_type="text")
                created_message = chat_service.create_chat_message(db, chat_message, agent_id=None, session_id=session.conversation_id, company_id=company_id, sender="user", attachments=attachments if attachments else None)

                await session_ws_manager.broadcast_to_session(
                    session.conversation_id, 
                    schemas_chat_message.ChatMessage.from_orm(created_message).json(), 
                    "user"
                )

                if not session.is_ai_enabled:
                    print(f"AI is disabled for session {session.conversation_id}. No response will be generated.")
                    return Response(status_code=200)

                # Check if a workflow is paused and waiting for input
                if session.next_step_id and session.workflow_id:
                    # Resume the paused workflow
                    workflow = workflow_service.get_workflow(db, session.workflow_id, company_id)
                    if workflow:
                        print(f"[WhatsApp] Resuming paused workflow {workflow.id} from step {session.next_step_id}")
                        workflow_exec_service = WorkflowExecutionService(db)
                        execution_result = await workflow_exec_service.execute_workflow(
                            user_message=message_text,
                            conversation_id=session.conversation_id,
                            company_id=company_id,
                            workflow=workflow,
                            attachments=attachments if attachments else None
                        )

                        # Handle execution result
                        if execution_result.get("status") == "completed":
                            response_text = execution_result.get("response", "Workflow completed.")
                            agent_message_schema = ChatMessageCreate(message=response_text, message_type="text")
                            db_agent_message = chat_service.create_chat_message(db, agent_message_schema, workflow.agent_id, session.conversation_id, company_id, "agent")

                            await messaging_service.send_whatsapp_message(
                                recipient_phone_number=sender_phone,
                                message_text=response_text,
                                integration=integration,
                                db=db
                            )

                            await session_ws_manager.broadcast_to_session(
                                session.conversation_id,
                                schemas_chat_message.ChatMessage.from_orm(db_agent_message).json(),
                                "agent"
                            )

                        elif execution_result.get("status") == "paused_for_prompt":
                            prompt_data = execution_result.get("prompt", {})
                            await messaging_service.send_whatsapp_interactive_message(
                                recipient_phone_number=sender_phone,
                                message_text=prompt_data.get("text", "Please choose an option:"),
                                options=prompt_data.get("options", []),
                                integration=integration,
                                db=db
                            )

                        elif execution_result.get("status") == "paused_for_input":
                            # Workflow is waiting for next user input - send the prompt if available
                            prompt_text = execution_result.get("prompt", {}).get("text")
                            if prompt_text:
                                await messaging_service.send_whatsapp_message(
                                    recipient_phone_number=sender_phone,
                                    message_text=prompt_text,
                                    integration=integration,
                                    db=db
                                )
                            print(f"[WhatsApp] Workflow paused for input in session {session.conversation_id}")

                        return Response(status_code=200)

                # Try trigger-based workflow finding first (new system)
                workflow = await workflow_trigger_service.find_workflow_for_channel_message(
                    db=db,
                    channel=TriggerChannel.WHATSAPP,
                    company_id=company_id,
                    message=message_text,
                    session_data={"session_id": session.conversation_id}
                )

                # Fallback to old similarity search if no trigger-based workflow found
                if not workflow:
                    workflow = workflow_service.find_similar_workflow(db, company_id=company_id, query=message_text)

                if not workflow:
                    print(f"No matching workflow found for message: '{message_text}'. Using default agent response.")
                    agents = agent_service.get_agents(db, company_id=company_id, limit=1)
                    if not agents:
                        print(f"Error: No agents found for company {company_id} to handle the response.")
                        return Response(status_code=200)
                    agent = agents[0]

                    agent_response = await agent_execution_service.generate_agent_response(
                        db, agent.id, session.conversation_id, session.conversation_id, company_id, message_text
                    )

                    # Check if LLM decided to trigger a workflow
                    if isinstance(agent_response, dict) and agent_response.get("type") == "workflow_trigger":
                        workflow_id = agent_response.get("workflow_id")
                        print(f"[WhatsApp] LLM triggered workflow {workflow_id}")
                        workflow = workflow_service.get_workflow(db, workflow_id, company_id)
                        if not workflow:
                            print(f"[WhatsApp] Workflow {workflow_id} not found")
                            return Response(status_code=200)
                        # Continue to workflow execution below
                    elif isinstance(agent_response, dict) and agent_response.get("type") == "handoff":
                        # LLM routing failed - notify user and initiate handoff
                        reason = agent_response.get("reason", "AI routing unavailable")
                        print(f"[WhatsApp] LLM failed, initiating handoff: {reason}")
                        error_msg = "I'm experiencing some technical difficulties. Let me connect you with a human agent who can help."
                        await messaging_service.send_whatsapp_message(
                            recipient_phone_number=sender_phone,
                            message_text=error_msg,
                            integration=integration,
                            db=db
                        )
                        # TODO: Trigger actual handoff to human agent here
                        return Response(status_code=200)
                    else:
                        # Regular text response from LLM
                        agent_response_text = agent_response if isinstance(agent_response, str) else str(agent_response)
                        print(agent_response_text)

                        agent_message_schema = ChatMessageCreate(message=agent_response_text, message_type="text")
                        db_agent_message = chat_service.create_chat_message(db, agent_message_schema, agent.id, session.conversation_id, company_id, "agent")

                        await messaging_service.send_whatsapp_message(
                            recipient_phone_number=sender_phone,
                            message_text=agent_response_text,
                            integration=integration,
                            db=db
                        )

                        await session_ws_manager.broadcast_to_session(
                            session.conversation_id,
                            schemas_chat_message.ChatMessage.from_orm(db_agent_message).json(),
                            "agent"
                        )
                        return Response(status_code=200)

                # --- Workflow Execution ---
                # Update session with workflow's agent_id (needed for handoff team lookup)
                if workflow.agent_id and session.agent_id != workflow.agent_id:
                    session.agent_id = workflow.agent_id
                    db.commit()
                    db.refresh(session)

                workflow_exec_service = WorkflowExecutionService(db)
                execution_result = await workflow_exec_service.execute_workflow(
                    workflow_id=workflow.id,
                    user_message=message_text,
                    conversation_id=session.conversation_id,
                    company_id=company_id,
                    attachments=attachments if attachments else None
                )

                if execution_result.get("status") == "completed":
                    response_text = execution_result.get("response", "Workflow completed.")
                    agent_message_schema = ChatMessageCreate(message=response_text, message_type="text")
                    db_agent_message = chat_service.create_chat_message(db, agent_message_schema, workflow.agent_id, session.conversation_id, company_id, "agent")
                    
                    await messaging_service.send_whatsapp_message(
                        recipient_phone_number=sender_phone,
                        message_text=response_text,
                        integration=integration,
                        db=db
                    )
                    
                    await session_ws_manager.broadcast_to_session(
                        session.conversation_id,
                        schemas_chat_message.ChatMessage.from_orm(db_agent_message).json(),
                        "agent"
                    )

                elif execution_result.get("status") == "paused_for_prompt":
                    prompt_data = execution_result.get("prompt", {})
                    await messaging_service.send_whatsapp_interactive_message(
                        recipient_phone_number=sender_phone,
                        message_text=prompt_data.get("text", "Please choose an option:"),
                        options=prompt_data.get("options", []),
                        integration=integration,
                        db=db
                    )
                
                elif execution_result.get("status") == "paused_for_input":
                    print(f"Workflow paused for input in session {session.conversation_id}")

                print(f"Processed message from {sender_phone} for company {company_id} with workflow '{workflow.name}'")

    except (KeyError, IndexError) as e:
        logging.error(f"Error parsing WhatsApp webhook data: {e}\n{traceback.format_exc()}")
        return Response(status_code=200)
    except Exception as e:
        logging.error(f"An unexpected error occurred: {e}\n{traceback.format_exc()}")
        return Response(status_code=200)

    return {"status": "ok"}
