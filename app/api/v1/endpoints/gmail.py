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
    credential_service,
    workflow_trigger_service
)
from app.services.workflow_execution_service import WorkflowExecutionService
from app.services.workflow_trigger_service import TriggerChannel
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

            # Reopen resolved sessions when a new message arrives
            if session.status == 'resolved':
                session = await conversation_session_service.reopen_resolved_session(db, session, company_id)
                logging.info(f"Reopened resolved session {session.conversation_id} for incoming Gmail message")

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

            # Check if a workflow is paused and waiting for input
            if session.next_step_id and session.workflow_id:
                # Resume the paused workflow
                workflow = workflow_service.get_workflow(db, session.workflow_id, company_id)
                if workflow:
                    logging.info(f"[Gmail] Resuming paused workflow {workflow.id} from step {session.next_step_id}")
                    workflow_exec_service = WorkflowExecutionService(db)
                    execution_result = await workflow_exec_service.execute_workflow(
                        user_message=message_text,
                        conversation_id=session.conversation_id,
                        company_id=company_id,
                        workflow=workflow
                    )

                    # Handle execution result
                    if execution_result.get("status") == "completed":
                        response_text = execution_result.get("response", "Workflow completed.")
                        agent_message_schema = ChatMessageCreate(message=response_text, message_type="text")
                        workflow_agent_id = session.agent_id or (workflow.agents[0].id if workflow.agents else None)
                        db_agent_message = chat_service.create_chat_message(db, agent_message_schema, workflow_agent_id, session.conversation_id, company_id, "agent")

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

                    elif execution_result.get("status") in ["paused_for_prompt", "paused_for_input"]:
                        prompt_text = execution_result.get("prompt", {}).get("text")
                        if prompt_text:
                            await messaging_service.send_gmail_message(
                                recipient_email=sender_email,
                                subject=f"Re: {subject}",
                                message_text=prompt_text,
                                integration=integration
                            )
                        logging.info(f"[Gmail] Workflow paused for input in session {session.conversation_id}")

                    return Response(status_code=200)

            # Priority: 1) Triggers, 2) LLM decision, 3) Similarity search
            workflow = None

            # 1. Try trigger-based workflow finding first
            try:
                workflow = await workflow_trigger_service.find_workflow_for_channel_message(
                    db=db,
                    channel=TriggerChannel.GMAIL,
                    company_id=company_id,
                    message=message_text,
                    session_data={"session_id": session.conversation_id}
                )
            except Exception as e:
                logging.error(f"[Gmail] Trigger service error: {e}")
                workflow = None

            if not workflow:
                # 2. No trigger match - try LLM-based routing (2nd priority)
                logging.info(f"[Gmail] No trigger match, trying LLM-based routing")
                agents = agent_service.get_agents(db, company_id=company_id, limit=1)
                if not agents:
                    logging.error(f"Error: No agents found for company {company_id} to handle the response.")
                    return Response(status_code=200)
                agent = agents[0]

                agent_response = await agent_execution_service.generate_agent_response(
                    db, agent.id, session.conversation_id, session.conversation_id, company_id, message_text
                )

                # Check if LLM decided to trigger a workflow (context-aware routing)
                if isinstance(agent_response, dict) and agent_response.get("type") == "workflow_trigger":
                    workflow_id = agent_response.get("workflow_id")
                    logging.info(f"[Gmail] LLM triggered workflow {workflow_id}")
                    workflow = workflow_service.get_workflow(db, workflow_id, company_id)
                    if not workflow:
                        logging.warning(f"[Gmail] Workflow {workflow_id} not found")
                        return Response(status_code=200)
                    # Continue to workflow execution below
                elif isinstance(agent_response, dict) and agent_response.get("type") == "handoff":
                    # LLM routing failed - notify user and initiate handoff
                    reason = agent_response.get("reason", "AI routing unavailable")
                    logging.warning(f"[Gmail] LLM failed, initiating handoff: {reason}")
                    error_msg = "I'm experiencing some technical difficulties. Let me connect you with a human agent who can help."
                    await messaging_service.send_gmail_message(
                        recipient_email=sender_email,
                        subject=f"Re: {subject}",
                        message_text=error_msg,
                        integration=integration
                    )
                    return Response(status_code=200)
                else:
                    # 3. LLM returned text - try similarity search as last fallback
                    logging.info(f"[Gmail] LLM returned text, trying similarity search as fallback")
                    workflow = workflow_service.find_similar_workflow(db, company_id=company_id, query=message_text, agent_id=session.agent_id)

                    if not workflow:
                        # No workflow found anywhere - use LLM's text response
                        agent_response_text = agent_response if isinstance(agent_response, str) else str(agent_response)

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
                agent_id=workflow_agent_id
            )

            if execution_result.get("status") == "completed":
                response_text = execution_result.get("response", "Workflow completed.")
                agent_message_schema = ChatMessageCreate(message=response_text, message_type="text")
                db_agent_message = chat_service.create_chat_message(db, agent_message_schema, workflow_agent_id, session.conversation_id, company_id, "agent")
                
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
