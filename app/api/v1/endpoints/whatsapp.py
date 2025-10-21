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

                chat_message = ChatMessageCreate(message=message_text, message_type="text")
                created_message = chat_service.create_chat_message(db, chat_message, agent_id=None, session_id=session.conversation_id, company_id=company_id, sender="user")

                await session_ws_manager.broadcast_to_session(
                    session.conversation_id, 
                    schemas_chat_message.ChatMessage.from_orm(created_message).json(), 
                    "user"
                )

                if not session.is_ai_enabled:
                    print(f"AI is disabled for session {session.conversation_id}. No response will be generated.")
                    return Response(status_code=200)

                workflow = workflow_service.find_similar_workflow(db, company_id=company_id, query=message_text)

                if not workflow:
                    print(f"No matching workflow found for message: '{message_text}'. Using default agent response.")
                    agents = agent_service.get_agents(db, company_id=company_id, limit=1)
                    if not agents:
                        print(f"Error: No agents found for company {company_id} to handle the response.")
                        return Response(status_code=200)
                    agent = agents[0]

                    agent_response_text = await agent_execution_service.generate_agent_response(
                        db, agent.id, session.conversation_id, company_id, message_text
                    )
                    
                    print(agent_response_text)

                    agent_message_schema = ChatMessageCreate(message=agent_response_text, message_type="text")
                    db_agent_message = chat_service.create_chat_message(db, agent_message_schema, agent.id, session.conversation_id, company_id, "agent")

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

                # --- Workflow Execution ---
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

    except (KeyError, IndexError) as e:
        logging.error(f"Error parsing WhatsApp webhook data: {e}\n{traceback.format_exc()}")
        return Response(status_code=200)
    except Exception as e:
        logging.error(f"An unexpected error occurred: {e}\n{traceback.format_exc()}")
        return Response(status_code=200)

    return {"status": "ok"}
