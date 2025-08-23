from fastapi import APIRouter, Request, Depends, HTTPException, Response
from sqlalchemy.orm import Session
import logging
import traceback
import google.oauth2.credentials
import google_auth_oauthlib.flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.core.dependencies import get_db, get_current_active_user
from app.core.config import settings
from app.services import (
    contact_service, 
    conversation_session_service, 
    chat_service, 
    workflow_service,
    integration_service, 
    messaging_service,
    agent_service,
    agent_execution_service,
    credential_service
)
from app.services.workflow_execution_service import WorkflowExecutionService
from app.schemas.chat_message import ChatMessageCreate
from app.schemas import chat_message as schemas_chat_message, credential as schemas_credential
from app.api.v1.endpoints.websocket_conversations import manager as session_ws_manager
from app.models.user import User

router = APIRouter()

@router.post("/webhook")
async def receive_message(request: Request, db: Session = Depends(get_db)):
    data = await request.json()
    logging.info(f"Received Gmail webhook data: {data}")

    try:
        # The actual parsing logic will depend on the Gmail API webhook format
        # This is a placeholder for now
        message = data.get("message")
        if message:
            # Extract relevant information from the message
            sender_email = message.get("from")
            subject = message.get("subject")
            message_text = message.get("body")
            
            # For now, we'll use a hardcoded integration for testing
            integration = integration_service.get_integration_by_type_and_company(db, "gmail", 1)
            if not integration:
                logging.error(f"Error: No active Gmail integration found.")
                return Response(status_code=200)

            company_id = integration.company_id
            contact = contact_service.get_or_create_contact_for_channel(
                db, 
                company_id=company_id, 
                channel='gmail', 
                channel_identifier=sender_email,
                name=sender_email
            )

            session = conversation_session_service.get_or_create_session(
                db, conversation_id=sender_email, workflow_id=None, contact_id=contact.id, channel='gmail', company_id=company_id
            )

            chat_message = ChatMessageCreate(message=message_text, message_type="text")
            created_message = chat_service.create_chat_message(db, chat_message, agent_id=None, session_id=session.conversation_id, company_id=company_id, sender="user")

            await session_ws_manager.broadcast_to_session(
                session.conversation_id, 
                schemas_chat_message.ChatMessage.from_orm(created_message).json(), 
                "user"
            )

            if not session.is_ai_enabled:
                logging.info(f"AI is disabled for session {session.conversation_id}. No response will be generated.")
                return Response(status_code=200)

            workflow = workflow_service.find_similar_workflow(db, company_id=company_id, query=message_text)

            if not workflow:
                logging.info(f"No matching workflow found for message: '{message_text}'. Using default agent response.")
                agents = agent_service.get_agents(db, company_id=company_id, limit=1)
                if not agents:
                    logging.error(f"Error: No agents found for company {company_id} to handle the response.")
                    return Response(status_code=200)
                agent = agents[0]

                agent_response_text = await agent_execution_service.generate_agent_response(
                    db, agent.id, session.conversation_id, company_id, message_text
                )

                if not agent_response_text:
                    logging.info(f"Agent did not generate a response for session {session.conversation_id}.")
                    return Response(status_code=200)

                agent_message_schema = ChatMessageCreate(message=agent_response_text, message_type="text")
                db_agent_message = chat_service.create_chat_message(db, agent_message_schema, agent.id, session.conversation_id, company_id, "agent")

                await messaging_service.send_gmail_message(
                    recipient_email=sender_email,
                    subject=f"Re: {subject}",
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
            execution_result = workflow_exec_service.execute_workflow(
                workflow_id=workflow.id,
                user_message=message_text,
                conversation_id=session.conversation_id
            )

            if execution_result.get("status") == "completed":
                response_text = execution_result.get("response", "Workflow completed.")
                agent_message_schema = ChatMessageCreate(message=response_text, message_type="text")
                db_agent_message = chat_service.create_chat_message(db, agent_message_schema, workflow.agent_id, session.conversation_id, company_id, "agent")
                
                await messaging_service.send_gmail_message(
                    recipient_email=sender_email,
                    subject=f"Re: {subject}",
                    message_text=response_text,
                    integration=integration
                )
                
                await session_ws_manager.broadcast_to_session(
                    session.conversation_id,
                    schemas_chat_message.ChatMessage.from_orm(db_agent_message).json(),
                    "agent"
                )
            
            logging.info(f"Processed Gmail message from {sender_email} for company {company_id} with workflow '{workflow.name}'")

    except (KeyError, IndexError) as e:
        logging.error(f"Error parsing Gmail webhook data: {e}\n{traceback.format_exc()}")
    except Exception as e:
        logging.error(f"An unexpected error occurred: {e}\n{traceback.format_exc()}")
    
    return Response(status_code=200)
