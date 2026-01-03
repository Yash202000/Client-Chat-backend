from fastapi import APIRouter, Request, Depends, HTTPException, Response
from sqlalchemy.orm import Session
import os
import logging
import traceback
import json

from app.core.dependencies import get_db
from app.core.config import settings
from app.services import contact_service, conversation_session_service, chat_service, integration_service, messaging_service
from app.services.connection_manager import manager
from app.schemas.chat_message import ChatMessageCreate
from app.schemas import session as schemas_session, websocket as schemas_websocket, chat_message as schemas_chat_message
from app.api.v1.endpoints.websocket_conversations import manager as session_ws_manager

router = APIRouter()

# This should be a secret value stored securely in your environment variables
VERIFY_TOKEN = settings.MESSENGER_VERIFY_TOKEN

@router.get("")
async def verify_webhook(request: Request):
    """
    Handles the webhook verification request from Meta for Messenger.
    """
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        print("Messenger webhook verified successfully!")
        return Response(content=challenge, status_code=200)
    else:
        print("Messenger webhook verification failed.")
        raise HTTPException(status_code=403, detail="Invalid verification token")

@router.post("")
async def receive_message(request: Request, db: Session = Depends(get_db)):
    """
    Handles incoming Messenger messages.
    """
    data = await request.json()
    print(f"Received Messenger webhook data: {data}")

    try:
        if data.get("object") == "page":
            for entry in data.get("entry", []):
                page_id = entry.get("id")
                for message_event in entry.get("messaging", []):
                    if message_event.get("message"):
                        sender_psid = message_event["sender"]["id"]
                        message_text = message_event["message"]["text"]

                        # --- Dynamic Company Lookup via Page ID ---
                        integration = integration_service.get_integration_by_page_id(db, page_id=page_id)
                        if not integration:
                            print(f"Error: No active Messenger integration found for page_id: {page_id}")
                            continue # Process next message event

                        company_id = integration.company_id
                        # TODO: The workflow should be dynamically assigned
                        workflow_id = 1 

                        # 1. Get or create a contact using the new centralized service
                        contact = contact_service.get_or_create_contact_for_channel(
                            db, 
                            company_id=company_id, 
                            channel='messenger', 
                            channel_identifier=sender_psid
                        )

                        # 2. Get or create a conversation session
                        session = conversation_session_service.get_or_create_session(db, conversation_id=sender_psid, workflow_id=workflow_id, contact_id=contact.id, channel='messenger', company_id=company_id)

                        # Reopen resolved sessions when a new message arrives
                        if session.status == 'resolved':
                            session = await conversation_session_service.reopen_resolved_session(db, session, company_id)
                            print(f"Reopened resolved session {session.conversation_id} for incoming Messenger message")

                        # Check for restart command ("0", "restart", "start over", "cancel", "reset")
                        if conversation_session_service.is_restart_command(message_text):
                            print(f"[Messenger] Restart command received from {sender_psid}")

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
                            await messaging_service.send_messenger_message(
                                recipient_psid=sender_psid,
                                message_text=confirmation,
                                integration=integration
                            )

                            # Save confirmation to chat history
                            agent_chat_message = ChatMessageCreate(message=confirmation, message_type="text")
                            agent_db_message = chat_service.create_chat_message(db, agent_chat_message, agent_id=None, session_id=session.conversation_id, company_id=company_id, sender="agent")

                            await session_ws_manager.broadcast_to_session(
                                session.conversation_id,
                                schemas_chat_message.ChatMessage.from_orm(agent_db_message).json(),
                                "agent"
                            )

                            continue  # Process next message event

                        # 3. Save the incoming message
                        chat_message = ChatMessageCreate(message=message_text, message_type="text")
                        chat_service.create_chat_message(db, message=chat_message, agent_id=None, session_id=session.conversation_id, company_id=company_id, sender="user")
                        
                        # 4. Broadcast the update
                        session_update_schema = schemas_websocket.WebSocketSessionUpdate.from_orm(session)
                        await manager.broadcast_to_company(
                            company_id,
                            json.dumps({"type": "new_message", "session": session_update_schema.dict(by_alias=True)})
                        )

                        print(f"Processed Messenger message from {sender_psid} for company {company_id}")

    except (KeyError, IndexError) as e:
        logging.error(f"Error parsing Messenger webhook data: {e}\n{traceback.format_exc()}")
    
    # Always return 200 OK to Meta
    return Response(status_code=200)
