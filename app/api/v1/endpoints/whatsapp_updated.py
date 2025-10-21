from fastapi import APIRouter, Request, Depends, HTTPException, Response
from sqlalchemy.orm import Session
import os
import logging
import traceback
import json

from app.core.dependencies import get_db
from app.core.config import settings
from app.services import (
    contact_service,
    conversation_session_service,
    chat_service,
    workflow_service,
    integration_service,
    messaging_service,
    agent_service,
    agent_execution_service
)
from app.services.intent_service import IntentService
from app.services.workflow_execution_service import WorkflowExecutionService
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

                if message_type == "text":
                    message_text = message_data["text"]["body"]
                elif message_type == "interactive":
                    interactive_type = message_data["interactive"]["type"]
                    if interactive_type == "button_reply":
                        message_text = message_data["interactive"]["button_reply"]["title"]
                    elif interactive_type == "list_reply":
                        message_text = message_data["interactive"]["list_reply"]["title"]
                    else:
                        print(f"Ignoring unknown interactive type: {interactive_type}")
                        return Response(status_code=200)
                else:
                    print(f"Ignoring non-text/interactive message type: {message_type}")
                    return Response(status_code=200)

                integration = integration_service.get_integration_by_phone_number_id(db, phone_number_id=phone_number_id)
                if not integration:
                    print(f"Error: No active integration found for phone_number_id: {phone_number_id}")
                    return Response(status_code=200)

                company_id = integration.company_id
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

                # Save user message
                chat_message = ChatMessageCreate(message=message_text, message_type="text")
                created_message = chat_service.create_chat_message(db, chat_message, agent_id=None, session_id=session.conversation_id, company_id=company_id, sender="user")

                # Broadcast user message to WebSocket
                await session_ws_manager.broadcast_to_session(
                    session.conversation_id,
                    schemas_chat_message.ChatMessage.from_orm(created_message).json(),
                    "user"
                )

                # Check if AI is enabled
                if not session.is_ai_enabled:
                    print(f"AI is disabled for session {session.conversation_id}. Agent must handle manually.")
                    # TODO: Notify assigned agent if any
                    return Response(status_code=200)

                # ============================================================
                # AUTOMATIC INTENT DETECTION & WORKFLOW TRIGGERING
                # ============================================================

                print(f"AI enabled for session {session.conversation_id}. Starting intent detection...")

                # STEP 1: Try Intent Detection
                intent_service = IntentService(db)
                intent_match = await intent_service.detect_intent(
                    message=message_text,
                    company_id=company_id,
                    conversation_id=session.conversation_id
                )

                if intent_match:
                    intent, confidence, entities, matched_method = intent_match
                    print(f"✓ Intent detected: {intent.name} (confidence: {confidence:.2f}, method: {matched_method})")

                    # Update session context with extracted entities
                    if entities:
                        current_context = session.context or {}
                        current_context.update(entities)
                        current_context['last_detected_intent'] = intent.name
                        current_context['intent_confidence'] = confidence
                        current_context['intent_matched_method'] = matched_method
                        conversation_session_service.update_session_context(
                            db, session.conversation_id, current_context
                        )
                        print(f"✓ Extracted entities: {entities}")

                    # Notify agents in background (non-blocking)
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
                        print(f"Warning: Could not broadcast intent detection: {e}")

                    # STEP 2: Check if intent should trigger a workflow automatically
                    if intent.trigger_workflow_id and intent.auto_trigger_enabled:
                        # Check confidence threshold
                        if confidence >= intent.min_confidence_auto_trigger:
                            workflow = workflow_service.get_workflow(db, intent.trigger_workflow_id, company_id)

                            if workflow and workflow.is_active:
                                print(f"✓ Auto-triggering workflow: {workflow.name} (ID: {workflow.id})")

                                # AUTOMATICALLY EXECUTE WORKFLOW
                                workflow_exec_service = WorkflowExecutionService(db)
                                execution_result = await workflow_exec_service.execute_workflow(
                                    workflow_id=workflow.id,
                                    user_message=message_text,
                                    conversation_id=session.conversation_id
                                )

                                # Update intent match with execution status
                                intent_service.update_intent_match_execution_status(
                                    conversation_id=session.conversation_id,
                                    intent_id=intent.id,
                                    workflow_executed=True,
                                    execution_status=execution_result.get("status", "unknown")
                                )

                                # Handle workflow execution results
                                if execution_result.get("status") == "completed":
                                    response_text = execution_result.get("response", "Workflow completed.")

                                    # Save agent message
                                    agent_message_schema = ChatMessageCreate(message=response_text, message_type="text")
                                    db_agent_message = chat_service.create_chat_message(
                                        db, agent_message_schema,
                                        workflow.agent_id,
                                        session.conversation_id,
                                        company_id,
                                        "agent"
                                    )

                                    # Send via WhatsApp
                                    await messaging_service.send_whatsapp_message(
                                        recipient_phone_number=sender_phone,
                                        message_text=response_text,
                                        integration=integration
                                    )

                                    # Broadcast to agent dashboard
                                    await session_ws_manager.broadcast_to_session(
                                        session.conversation_id,
                                        schemas_chat_message.ChatMessage.from_orm(db_agent_message).json(),
                                        "agent"
                                    )

                                    print(f"✓ Workflow completed successfully")
                                    return Response(status_code=200)

                                elif execution_result.get("status") == "paused_for_prompt":
                                    # Workflow needs user input (interactive buttons/lists)
                                    prompt_data = execution_result.get("prompt", {})
                                    await messaging_service.send_whatsapp_interactive_message(
                                        recipient_phone_number=sender_phone,
                                        message_text=prompt_data.get("text", "Please choose an option:"),
                                        options=prompt_data.get("options", []),
                                        integration=integration
                                    )
                                    print(f"✓ Workflow paused for user input")
                                    return Response(status_code=200)

                                elif execution_result.get("status") == "paused_for_input":
                                    # Workflow waiting for text input
                                    print(f"✓ Workflow paused, waiting for user input")
                                    return Response(status_code=200)

                                elif execution_result.get("status") == "error":
                                    # Workflow failed - fallback to agent
                                    error_msg = execution_result.get("error", "Unknown error")
                                    print(f"✗ Workflow execution failed: {error_msg}")
                                    intent_service.update_intent_match_execution_status(
                                        conversation_id=session.conversation_id,
                                        intent_id=intent.id,
                                        workflow_executed=False,
                                        execution_status="error"
                                    )
                                    # Continue to fallback below

                            else:
                                print(f"✗ Workflow {intent.trigger_workflow_id} not found or inactive")
                        else:
                            print(f"ℹ Confidence {confidence:.2f} below threshold {intent.min_confidence_auto_trigger}, not auto-triggering")
                    else:
                        print(f"ℹ Intent '{intent.name}' has no workflow or auto-trigger disabled")

                # STEP 3: Fallback - No intent matched or workflow failed/not configured
                print(f"Falling back to find_similar_workflow or default agent response...")

                workflow = workflow_service.find_similar_workflow(db, company_id=company_id, query=message_text)

                if workflow:
                    print(f"✓ Found similar workflow: {workflow.name}")
                    # Execute workflow (existing logic)
                    workflow_exec_service = WorkflowExecutionService(db)
                    execution_result = await workflow_exec_service.execute_workflow(
                        workflow_id=workflow.id,
                        user_message=message_text,
                        conversation_id=session.conversation_id
                    )

                    if execution_result.get("status") == "completed":
                        response_text = execution_result.get("response", "Workflow completed.")
                        agent_message_schema = ChatMessageCreate(message=response_text, message_type="text")
                        db_agent_message = chat_service.create_chat_message(db, agent_message_schema, workflow.agent_id, session.conversation_id, company_id, "agent")

                        await messaging_service.send_whatsapp_message(
                            recipient_phone_number=sender_phone,
                            message_text=response_text,
                            integration=integration
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
                            integration=integration
                        )

                    elif execution_result.get("status") == "paused_for_input":
                        print(f"Workflow paused for input in session {session.conversation_id}")

                    print(f"Processed message from {sender_phone} for company {company_id} with workflow '{workflow.name}'")
                    return Response(status_code=200)

                # FINAL FALLBACK: Use default agent LLM response
                print(f"✓ Using default agent response")
                agents = agent_service.get_agents(db, company_id=company_id, limit=1)
                if not agents:
                    print(f"✗ No agents found for company {company_id}")
                    return Response(status_code=200)

                agent = agents[0]

                agent_response_text = await agent_execution_service.generate_agent_response(
                    db, agent.id, session.conversation_id, company_id, message_text
                )

                agent_message_schema = ChatMessageCreate(message=agent_response_text, message_type="text")
                db_agent_message = chat_service.create_chat_message(
                    db, agent_message_schema,
                    agent.id,
                    session.conversation_id,
                    company_id,
                    "agent"
                )

                await messaging_service.send_whatsapp_message(
                    recipient_phone_number=sender_phone,
                    message_text=agent_response_text,
                    integration=integration
                )

                await session_ws_manager.broadcast_to_session(
                    session.conversation_id,
                    schemas_chat_message.ChatMessage.from_orm(db_agent_message).json(),
                    "agent"
                )

                return Response(status_code=200)

    except (KeyError, IndexError) as e:
        logging.error(f"Error parsing WhatsApp webhook data: {e}\n{traceback.format_exc()}")
        return Response(status_code=200)
    except Exception as e:
        logging.error(f"An unexpected error occurred: {e}\n{traceback.format_exc()}")
        return Response(status_code=200)

    return {"status": "ok"}
