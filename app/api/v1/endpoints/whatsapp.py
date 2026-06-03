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
from app.services.intent_service import IntentService
from app.models.workflow_trigger import TriggerChannel
from app.services.connection_manager import manager
from app.services import cod_service, ctwa_service, webhook_delivery_service
from app.services import opt_out_service
from app.schemas.chat_message import ChatMessageCreate
from app.schemas import websocket as schemas_websocket, chat_message as schemas_chat_message
from app.api.v1.endpoints.websocket_conversations import manager as session_ws_manager
logger = logging.getLogger(__name__)

router = APIRouter()

VERIFY_TOKEN = settings.WHATSAPP_VERIFY_TOKEN

@router.get("")
async def verify_webhook(request: Request):
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        return Response(content=challenge, status_code=200)
    else:
        raise HTTPException(status_code=403, detail="Invalid verification token")

@router.post("")
async def receive_message(request: Request, db: Session = Depends(get_db)):
    data = await request.json()

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
                        return Response(status_code=200)
                elif message_type in ["image", "document", "audio", "video"]:
                    # Handle media messages
                    media_data = message_data.get(message_type, {})
                    media_id = media_data.get("id")

                    if not media_id:
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
                else:
                    return Response(status_code=200)

                integration = integration_service.get_integration_by_phone_number_id(db, phone_number_id=phone_number_id)
                if not integration:
                    return Response(status_code=200)

                company_id = integration.company_id

                # Save original user input (caption/text) before attachment processing
                # This prevents auto-generated filenames from triggering restart detection
                original_user_input = message_text

                # Download and process media if this is a media message
                if pending_media:
                    try:
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

                        # If no caption was provided, use attachment text as message
                        if not message_text:
                            message_text = attachment_text

                    except Exception as e:
                        # Continue processing without attachment if download fails
                        if not message_text:
                            message_text = f"[Media attachment - {pending_media['media_type']}]"

                wa_profile_name = change.get("value", {}).get("contacts", [{}])[0].get("profile", {}).get("name")

                # COD reply intercept — check before normal chat flow
                if message_text:
                    cod_consumed = await cod_service.handle_cod_reply(
                        db=db,
                        company_id=company_id,
                        sender_phone=sender_phone,
                        message_text=message_text,
                    )
                    if cod_consumed:
                        return Response(status_code=200)

                # Opt-out / opt-in handling — must run before contact creation
                if message_type == "text" and message_text:
                    if opt_out_service.is_opt_out_message(message_text):
                        opt_out_service.opt_out_contact(db, company_id, sender_phone)
                        try:
                            await messaging_service.send_whatsapp_message(
                                recipient_phone_number=sender_phone,
                                message_text="You've been unsubscribed from broadcast messages. Reply START to re-subscribe.",
                                integration=integration,
                                db=db,
                            )
                        except Exception:
                            pass
                        return Response(status_code=200)
                    elif opt_out_service.is_opt_in_message(message_text):
                        opt_out_service.opt_in_contact(db, company_id, sender_phone)

                contact = contact_service.get_or_create_contact_for_channel(
                    db,
                    company_id=company_id,
                    channel='whatsapp',
                    channel_identifier=sender_phone,
                    name=wa_profile_name
                )

                # CTWA attribution — tag contact + trigger workflow if they came via a tracked link
                await ctwa_service.attribute_ctwa_contact(
                    db=db,
                    company_id=company_id,
                    sender_phone=sender_phone,
                    contact=contact,
                )

                session = conversation_session_service.get_or_create_session(
                    db, conversation_id=sender_phone, workflow_id=None, contact_id=contact.id, channel='whatsapp', company_id=company_id
                )

                # Reopen resolved sessions when a new message arrives
                if session.status == 'resolved':
                    session = await conversation_session_service.reopen_resolved_session(db, session, company_id)

                # Check for restart command ("0", "restart", "start over", "cancel", "reset")
                # Only check on original user input, not auto-generated attachment filenames
                if original_user_input and conversation_session_service.is_restart_command(original_user_input):

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
                    return Response(status_code=200)

                # Check if a workflow is paused and waiting for input
                if session.next_step_id and session.workflow_id:
                    # Resume the paused workflow
                    workflow = workflow_service.get_workflow(db, session.workflow_id, company_id)
                    if workflow:
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
                            workflow_agent_id = session.agent_id or (workflow.agents[0].id if workflow.agents else None)
                            db_agent_message = chat_service.create_chat_message(db, agent_message_schema, workflow_agent_id, session.conversation_id, company_id, "agent")

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

                        return Response(status_code=200)

                # Priority: 1) Intent detection, 2) Triggers, 3) LLM decision, 4) Similarity search

                # 1. Try intent detection first
                intent_service = IntentService(db)
                intent_match = await intent_service.detect_intent(
                    message=message_text,
                    company_id=company_id,
                    conversation_id=session.conversation_id
                )

                if intent_match:
                    intent, confidence, entities, matched_method = intent_match

                    if entities:
                        current_context = session.context or {}
                        current_context.update(entities)
                        current_context['last_detected_intent'] = intent.name
                        current_context['intent_confidence'] = confidence
                        current_context['intent_matched_method'] = matched_method
                        conversation_session_service.update_session_context(db, session.conversation_id, current_context)

                    try:
                        await session_ws_manager.broadcast_intent_detected(
                            session.conversation_id,
                            {
                                "intent_name": intent.name,
                                "confidence": confidence,
                                "matched_method": matched_method,
                                "entities": entities,
                                "will_trigger_workflow": bool(intent.trigger_workflow_id and intent.auto_trigger_enabled)
                            }
                        )
                    except Exception as e:
                        logger.exception(e)

                    if intent.trigger_workflow_id and intent.auto_trigger_enabled:
                        if confidence >= intent.min_confidence_auto_trigger:
                            intent_workflow = workflow_service.get_workflow(db, intent.trigger_workflow_id, company_id)

                            if intent_workflow and intent_workflow.is_active:
                                workflow_exec_service = WorkflowExecutionService(db)
                                execution_result = await workflow_exec_service.execute_workflow(
                                    workflow_id=intent_workflow.id,
                                    user_message=message_text,
                                    conversation_id=session.conversation_id,
                                    company_id=company_id,
                                    attachments=attachments if attachments else None,
                                    agent_id=session.agent_id or (intent_workflow.agents[0].id if intent_workflow.agents else None)
                                )

                                intent_service.update_intent_match_execution_status(
                                    conversation_id=session.conversation_id,
                                    intent_id=intent.id,
                                    workflow_executed=True,
                                    execution_status=execution_result.get("status", "unknown")
                                )

                                if execution_result.get("status") == "completed":
                                    response_text = execution_result.get("response", "Workflow completed.")
                                    workflow_agent_id = session.agent_id or (intent_workflow.agents[0].id if intent_workflow.agents else None)
                                    agent_message_schema = ChatMessageCreate(message=response_text, message_type="text")
                                    db_agent_message = chat_service.create_chat_message(db, agent_message_schema, workflow_agent_id, session.conversation_id, company_id, "agent")
                                    await messaging_service.send_whatsapp_message(recipient_phone_number=sender_phone, message_text=response_text, integration=integration, db=db)
                                    await session_ws_manager.broadcast_to_session(session.conversation_id, schemas_chat_message.ChatMessage.from_orm(db_agent_message).json(), "agent")
                                    return Response(status_code=200)

                                elif execution_result.get("status") == "paused_for_prompt":
                                    prompt_data = execution_result.get("prompt", {})
                                    await messaging_service.send_whatsapp_interactive_message(recipient_phone_number=sender_phone, message_text=prompt_data.get("text", "Please choose an option:"), options=prompt_data.get("options", []), integration=integration, db=db)
                                    return Response(status_code=200)

                                elif execution_result.get("status") == "paused_for_input":
                                    return Response(status_code=200)

                                elif execution_result.get("status") == "error":
                                    pass
                            else:
                                pass
                        else:
                            pass
                    else:
                        pass

                workflow = await workflow_trigger_service.find_workflow_for_channel_message(
                    db=db,
                    channel=TriggerChannel.WHATSAPP,
                    company_id=company_id,
                    message=message_text,
                    session_data={"session_id": session.conversation_id}
                )

                if not workflow:
                    # 2. No trigger match - try LLM-based routing (2nd priority)
                    agents = agent_service.get_agents(db, company_id=company_id, limit=1)
                    if not agents:
                        return Response(status_code=200)
                    agent = agents[0]

                    agent_response = await agent_execution_service.generate_agent_response(
                        db, agent.id, session.conversation_id, session.conversation_id, company_id, message_text
                    )

                    # Check if LLM decided to trigger a workflow (context-aware routing)
                    if isinstance(agent_response, dict) and agent_response.get("type") == "workflow_trigger":
                        workflow_id = agent_response.get("workflow_id")
                        workflow = workflow_service.get_workflow(db, workflow_id, company_id)
                        if not workflow:
                            return Response(status_code=200)
                        # Continue to workflow execution below
                    elif isinstance(agent_response, dict) and agent_response.get("type") == "handoff":
                        # LLM routing failed - notify user and initiate handoff
                        reason = agent_response.get("reason", "AI routing unavailable")
                        error_msg = "I'm experiencing some technical difficulties. Let me connect you with a human agent who can help."
                        await messaging_service.send_whatsapp_message(
                            recipient_phone_number=sender_phone,
                            message_text=error_msg,
                            integration=integration,
                            db=db
                        )
                        return Response(status_code=200)
                    else:
                        # 3. LLM returned text - try similarity search as last fallback
                        workflow = workflow_service.find_similar_workflow(db, company_id=company_id, query=message_text, agent_id=session.agent_id)

                        if not workflow:
                            # No workflow found anywhere - use LLM's text response
                            agent_response_text = agent_response if isinstance(agent_response, str) else str(agent_response)

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
                # Get agent_id from workflow's agents (many-to-many) or use session's agent_id
                workflow_agent_id = session.agent_id or (workflow.agents[0].id if workflow.agents else None)
                # Update session with workflow's agent_id (needed for handoff team lookup)
                if workflow_agent_id and session.agent_id != workflow_agent_id:
                    session.agent_id = workflow_agent_id
                    db.commit()
                    db.refresh(session)

                workflow_exec_service = WorkflowExecutionService(db)
                execution_result = await workflow_exec_service.execute_workflow(
                    workflow_id=workflow.id,
                    user_message=message_text,
                    conversation_id=session.conversation_id,
                    company_id=company_id,
                    attachments=attachments if attachments else None,
                    agent_id=workflow_agent_id
                )

                if execution_result.get("status") == "completed":
                    response_text = execution_result.get("response", "Workflow completed.")
                    agent_message_schema = ChatMessageCreate(message=response_text, message_type="text")
                    db_agent_message = chat_service.create_chat_message(db, agent_message_schema, workflow_agent_id, session.conversation_id, company_id, "agent")
                    
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
                    pass


        # Handle message status updates (delivered, read, failed)
        if change.get("field") == "messages" and "statuses" in change.get("value", {}):
            statuses = change["value"]["statuses"]
            phone_number_id_val = change.get("value", {}).get("metadata", {}).get("phone_number_id")
            for status_item in statuses:
                msg_id = status_item.get("id")
                recipient = status_item.get("recipient_id")
                status_val = status_item.get("status")  # "sent", "delivered", "read", "failed"

                if status_val in ("delivered", "read", "failed"):
                    event_type = f"message.{status_val}"
                    payload = {
                        "event": event_type,
                        "message_id": msg_id,
                        "recipient": recipient,
                        "timestamp": status_item.get("timestamp"),
                    }
                    # Find which company owns this phone_number_id
                    wa_integration = integration_service.get_integration_by_phone_number_id(
                        db, phone_number_id_val or ""
                    )
                    if wa_integration:
                        import asyncio
                        asyncio.create_task(
                            webhook_delivery_service.fire_company_webhooks(
                                db, wa_integration.company_id, event_type, payload
                            )
                        )

    except (KeyError, IndexError) as e:
        logging.error(f"Error parsing WhatsApp webhook data: {e}\n{traceback.format_exc()}")
        return Response(status_code=200)
    except Exception as e:
        logging.error(f"An unexpected error occurred: {e}\n{traceback.format_exc()}")
        return Response(status_code=200)

    return {"status": "ok"}
