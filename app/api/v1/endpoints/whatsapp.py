from fastapi import APIRouter, Request, Depends, HTTPException, Response
from sqlalchemy.orm import Session
import os
import logging
import traceback
import json

from app.core.dependencies import get_db
from app.core.config import settings
from app.services import contact_service, conversation_session_service, chat_service, workflow_execution_service, integration_service, agent_service, agent_execution_service, messaging_service
from app.services.connection_manager import manager
from app.schemas.chat_message import ChatMessageCreate
from app.schemas import session as schemas_session, websocket as schemas_websocket, chat_message as schemas_chat_message
from app.api.v1.endpoints.websocket_conversations import manager as session_ws_manager

router = APIRouter()

# This should be a secret value stored securely in your environment variables
VERIFY_TOKEN = settings.WHATSAPP_VERIFY_TOKEN

@router.get("")
async def verify_webhook(request: Request):
    """
    Handles the webhook verification request from Meta.
    """
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
    """
    Handles incoming WhatsApp messages.
    """
    data = await request.json()
    print(f"Received webhook data: {data}") # For debugging purposes

    try:
        if "entry" in data and data["entry"]:
            change = data["entry"][0]["changes"][0]
            # Ensure the change is a message and not a status update or other event
            if change.get("field") == "messages" and "messages" in change.get("value", {}):
                # Extract identifiers from the payload
                phone_number_id = change["value"]["metadata"]["phone_number_id"]
                message_data = change["value"]["messages"][0]
                
                # Ignore messages that are not of type 'text' for now
                if message_data.get("type") != "text":
                    print(f"Ignoring non-text message type: {message_data.get('type')}")
                    return Response(status_code=200)

                sender_phone = message_data["from"]
                message_text = message_data["text"]["body"]

                # --- Dynamic Company Lookup ---
                integration = integration_service.get_integration_by_phone_number_id(db, phone_number_id=phone_number_id)
                if not integration:
                    print(f"Error: No active integration found for phone_number_id: {phone_number_id}")
                    return Response(status_code=200) # Return OK to prevent Meta retries

                company_id = integration.company_id
                # TODO: The workflow should be dynamically assigned, e.g., a default inbound workflow for the company
                workflow_id = 1 

                # 1. Get or create a contact using the new centralized service
                contact = contact_service.get_or_create_contact_for_channel(
                    db, 
                    company_id=company_id, 
                    channel='whatsapp', 
                    channel_identifier=sender_phone,
                    name=change.get("value", {}).get("contacts", [{}])[0].get("profile", {}).get("name")
                )

                # 2. Get or create a conversation session
                session = conversation_session_service.get_or_create_session(db, conversation_id=sender_phone, workflow_id=workflow_id, contact_id=contact.id, channel='whatsapp', company_id=company_id)

                # 3. Save the incoming message
                chat_message = ChatMessageCreate(message=message_text, message_type="text")
                created_message = chat_service.create_chat_message(db, chat_message, agent_id=None, session_id=session.conversation_id, company_id=company_id, sender="user")

                # 4. Broadcast the update to all connected clients for the company
                session_update_schema = schemas_websocket.WebSocketSessionUpdate.from_orm(session)
                await manager.broadcast_to_company(
                    company_id, 
                    json.dumps({"type": "new_message", "session": session_update_schema.dict(by_alias=True)})
                )

                # 5. Broadcast the new message to the session-specific WebSocket
                await session_ws_manager.broadcast_to_session(
                    session.conversation_id, 
                    schemas_chat_message.ChatMessage.from_orm(created_message).json(), 
                    "user" # Assuming messages from webhooks are always from the user
                )

                # --- Agent Response Generation ---
                # 6. Get the default agent for the company
                agents = agent_service.get_agents(db, company_id=company_id, limit=1)
                if not agents:
                    print(f"Error: No agents found for company {company_id} to handle the response.")
                    return Response(status_code=200)
                
                agent = agents[0]

                # 7. Generate agent response
                agent_response_text = agent_execution_service.generate_agent_response(
                    db, agent.id, session.conversation_id, company_id, message_text
                )

                # 8. Save the agent's message
                agent_message_schema = ChatMessageCreate(message=agent_response_text, message_type="text")
                db_agent_message = chat_service.create_chat_message(db, agent_message_schema, agent.id, session.conversation_id, company_id, "agent")

                # 9. Send the response back to WhatsApp
                await messaging_service.send_whatsapp_message(
                    recipient_phone_number=sender_phone,
                    message_text=agent_response_text,
                    integration=integration
                )

                # 10. Broadcast the agent's message to the dashboard
                await session_ws_manager.broadcast_to_session(
                    session.conversation_id,
                    schemas_chat_message.ChatMessage.from_orm(db_agent_message).json(),
                    "agent"
                )
                
                print(f"Processed message from {sender_phone} for company {company_id}")

    except (KeyError, IndexError) as e:
        logging.error(f"Error parsing WhatsApp webhook data: {e}\n{traceback.format_exc()}")
        return Response(status_code=200)

    return {"status": "ok"}
