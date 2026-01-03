from fastapi import APIRouter, Request, Depends, HTTPException, Response
from sqlalchemy.orm import Session
import logging
import traceback

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
from app.schemas.chat_message import ChatMessageCreate
from app.schemas import chat_message as schemas_chat_message
from app.api.v1.endpoints.websocket_conversations import manager as session_ws_manager

router = APIRouter()

@router.post("")
async def receive_linkedin_message(request: Request, db: Session = Depends(get_db)):
    data = await request.json()
    print(f"Received LinkedIn webhook data: {data}")

    try:
        # LinkedIn webhook structure is different. We need to parse it accordingly.
        # This is an educated guess based on common webhook patterns.
        # The actual payload structure should be verified with LinkedIn's documentation.
        if "entry" in data and data["entry"]:
            for entry in data["entry"]:
                for message_event in entry.get("messaging", []):
                    if "message" in message_event:
                        # This is where you would extract the LinkedIn Company ID from the payload
                        # For now, we'll use the one from the settings.
                        linkedin_company_id = settings.LINKEDIN_COMPANY_ID
                        
                        integration = integration_service.get_integration_by_linkedin_company_id(db, linkedin_company_id=linkedin_company_id)
                        if not integration:
                            print(f"Error: No active integration found for linkedin_company_id: {linkedin_company_id}")
                            continue

                        sender_id = message_event["sender"]["id"]
                        message_text = message_event["message"]["text"]
                        
                        company_id = integration.company_id
                        contact = contact_service.get_or_create_contact_for_channel(
                            db, 
                            company_id=company_id, 
                            channel='linkedin', 
                            channel_identifier=sender_id,
                            name=f"LinkedIn User {sender_id}" # Placeholder name
                        )

                        session = conversation_session_service.get_or_create_session(
                            db,
                            conversation_id=sender_id,
                            workflow_id=None,
                            contact_id=contact.id,
                            channel='linkedin',
                            company_id=company_id
                        )

                        # Reopen resolved sessions when a new message arrives
                        if session.status == 'resolved':
                            session = await conversation_session_service.reopen_resolved_session(db, session, company_id)
                            print(f"Reopened resolved session {session.conversation_id} for incoming LinkedIn message")

                        chat_message = ChatMessageCreate(message=message_text, message_type="text")
                        created_message = chat_service.create_chat_message(db, chat_message, agent_id=None, session_id=session.conversation_id, company_id=company_id, sender="user")

                        await session_ws_manager.broadcast_to_session(
                            session.conversation_id, 
                            schemas_chat_message.ChatMessage.from_orm(created_message).json(), 
                            "user"
                        )

                        if not session.is_ai_enabled:
                            print(f"AI is disabled for session {session.conversation_id}. No response will be generated.")
                            continue

                        # For now, we'll just use the default agent response
                        agents = agent_service.get_agents(db, company_id=company_id, limit=1)
                        if not agents:
                            print(f"Error: No agents found for company {company_id} to handle the response.")
                            continue
                        agent = agents[0]

                        agent_response_text = await agent_execution_service.generate_agent_response(
                            db, agent.id, session.conversation_id, company_id, message_text
                        )
                        
                        agent_message_schema = ChatMessageCreate(message=agent_response_text, message_type="text")
                        db_agent_message = chat_service.create_chat_message(db, agent_message_schema, agent.id, session.conversation_id, company_id, "agent")

                        # The messaging_service needs a send_linkedin_message function
                        # For now, this will call a placeholder function
                        await messaging_service.send_linkedin_message(
                            recipient_urn=sender_id,
                            message_text=agent_response_text,
                            integration=integration
                        )

                        await session_ws_manager.broadcast_to_session(
                            session.conversation_id,
                            schemas_chat_message.ChatMessage.from_orm(db_agent_message).json(),
                            "agent"
                        )

    except (KeyError, IndexError) as e:
        logging.error(f"Error parsing LinkedIn webhook data: {e}\n{traceback.format_exc()}")
    except Exception as e:
        logging.error(f"An unexpected error occurred: {e}\n{traceback.format_exc()}")

    return Response(status_code=200)