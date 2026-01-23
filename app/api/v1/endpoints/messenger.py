from fastapi import APIRouter, Request, Depends, HTTPException, Response
from sqlalchemy.orm import Session
import logging
import traceback
import httpx
import base64

from app.core.dependencies import get_db
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
from app.schemas.chat_message import ChatMessageCreate
from app.schemas import chat_message as schemas_chat_message
from app.api.v1.endpoints.websocket_conversations import manager as session_ws_manager, process_attachments_for_storage

router = APIRouter()

VERIFY_TOKEN = settings.MESSENGER_VERIFY_TOKEN


async def download_messenger_media(url: str, access_token: str) -> dict:
    """
    Downloads media from Messenger URL and returns it in the same format as WhatsApp media.
    Messenger media URLs require the access token as a query parameter.

    Returns:
        Dict with 'data' (bytes), 'mime_type', and 'extension'
    """
    # Messenger media URLs need the access token appended
    if "?" in url:
        download_url = f"{url}&access_token={access_token}"
    else:
        download_url = f"{url}?access_token={access_token}"

    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            response = await client.get(download_url)
            response.raise_for_status()

            file_data = response.content
            content_type = response.headers.get("content-type", "application/octet-stream")

            # Extract mime type (strip charset if present)
            mime_type = content_type.split(";")[0].strip()

            # Generate filename based on mime type
            extension_map = {
                "image/jpeg": ".jpg",
                "image/png": ".png",
                "image/webp": ".webp",
                "image/gif": ".gif",
                "video/mp4": ".mp4",
                "audio/mpeg": ".mp3",
                "audio/mp4": ".m4a",
            }
            extension = extension_map.get(mime_type, "")

            logging.info(f"[Messenger Media] Downloaded {len(file_data)} bytes, mime_type: {mime_type}")

            return {
                "data": file_data,
                "mime_type": mime_type,
                "extension": extension
            }
        except Exception as e:
            logging.error(f"Error downloading Messenger media from {url}: {e}")
            raise e


@router.get("")
async def verify_webhook(request: Request):
    """
    Handles the webhook verification request from Meta for Messenger.
    """
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        logging.info("Messenger webhook verified successfully!")
        return Response(content=challenge, status_code=200)
    else:
        logging.error("Messenger webhook verification failed.")
        raise HTTPException(status_code=403, detail="Invalid verification token")


@router.post("")
async def receive_message(request: Request, db: Session = Depends(get_db)):
    """
    Handles incoming Messenger messages with full workflow support.
    """
    data = await request.json()
    logging.info(f"Received Messenger webhook data: {data}")

    try:
        if data.get("object") == "page":
            for entry in data.get("entry", []):
                page_id = entry.get("id")
                for message_event in entry.get("messaging", []):
                    # Skip echo messages (messages sent by the page itself)
                    if message_event.get("message", {}).get("is_echo"):
                        continue

                    # Process messages that have text OR attachments
                    if message_event.get("message") and ("text" in message_event["message"] or "attachments" in message_event["message"]):
                        sender_id = message_event["sender"]["id"]
                        message_text = message_event["message"].get("text", "")

                        # --- Dynamic Company Lookup via Page ID ---
                        integration = integration_service.get_integration_by_page_id(db, page_id=page_id)
                        if not integration:
                            logging.error(f"Error: No active Messenger integration found for page_id: {page_id}")
                            continue

                        company_id = integration.company_id

                        # Get access token for media downloads
                        credentials = integration_service.get_decrypted_credentials(integration)
                        access_token = credentials.get("page_access_token") or credentials.get("access_token")

                        # Extract and download attachments if present
                        attachments = []
                        if "attachments" in message_event["message"]:
                            for att in message_event["message"]["attachments"]:
                                att_type = att.get("type", "file")
                                att_url = att.get("payload", {}).get("url", "")

                                # Handle location attachments
                                if att_type == "location":
                                    coordinates = att.get("payload", {}).get("coordinates", {})
                                    if coordinates:
                                        attachments.append({
                                            "file_name": "location",
                                            "file_type": "application/geo+json",
                                            "file_size": 46,
                                            "location": {
                                                "latitude": coordinates.get("lat"),
                                                "longitude": coordinates.get("long")
                                            }
                                        })
                                        logging.info(f"[Messenger] Received location: {coordinates}")
                                elif att_url:
                                    try:
                                        # Download media from Messenger URL and convert to base64
                                        logging.info(f"[Messenger] Downloading {att_type} media from URL")
                                        media_result = await download_messenger_media(att_url, access_token)
                                        file_data_base64 = base64.b64encode(media_result["data"]).decode('utf-8')

                                        attachment = {
                                            "file_data": file_data_base64,
                                            "file_name": f"messenger_{att_type}{media_result['extension']}",
                                            "file_type": media_result["mime_type"],
                                            "file_size": len(media_result["data"])
                                        }
                                        attachments.append(attachment)
                                        logging.info(f"[Messenger] Downloaded attachment: {attachment['file_name']}, size: {attachment['file_size']} bytes")
                                    except Exception as e:
                                        logging.error(f"[Messenger] Failed to download attachment: {e}")
                                        # Fallback to URL-based attachment if download fails
                                        attachments.append({
                                            "type": att_type,
                                            "url": att_url,
                                            "name": f"messenger_{att_type}"
                                        })

                            logging.info(f"[Messenger] Processed {len(attachments)} attachment(s)")

                            # If no text but has attachments, use attachment info as message
                            if not message_text and attachments:
                                if attachments[0].get("location"):
                                    loc = attachments[0]["location"]
                                    message_text = f"📍 Location ({loc['latitude']:.4f}, {loc['longitude']:.4f})"
                                else:
                                    att_name = attachments[0].get('file_name', attachments[0].get('name', 'attachment'))
                                    message_text = f"[Attachment: {att_name}]"

                        # Get or create contact
                        contact = contact_service.get_or_create_contact_for_channel(
                            db,
                            company_id=company_id,
                            channel='messenger',
                            channel_identifier=sender_id,
                            name=None
                        )

                        # Get or create session
                        session = conversation_session_service.get_or_create_session(
                            db, conversation_id=sender_id, workflow_id=None, contact_id=contact.id, channel='messenger', company_id=company_id
                        )

                        # Reopen resolved sessions when a new message arrives
                        if session.status == 'resolved':
                            session = await conversation_session_service.reopen_resolved_session(db, session, company_id)
                            logging.info(f"Reopened resolved session {session.conversation_id} for incoming Messenger message")

                        # Check for restart command ("0", "restart", "start over", "cancel", "reset")
                        if conversation_session_service.is_restart_command(message_text):
                            logging.info(f"[Messenger] Restart command received from {sender_id}")

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
                                recipient_psid=sender_id,
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

                            continue

                        # Save incoming message to chat history
                        chat_message = ChatMessageCreate(message=message_text, message_type="text")
                        created_message = chat_service.create_chat_message(db, chat_message, agent_id=None, session_id=session.conversation_id, company_id=company_id, sender="user")

                        await session_ws_manager.broadcast_to_session(
                            session.conversation_id,
                            schemas_chat_message.ChatMessage.from_orm(created_message).json(),
                            "user"
                        )

                        # Check if AI is enabled for this session
                        if not session.is_ai_enabled:
                            logging.info(f"AI is disabled for session {session.conversation_id}. No response will be generated.")
                            continue

                        # Check if a workflow is paused and waiting for input
                        if session.next_step_id and session.workflow_id:
                            # Resume the paused workflow
                            workflow = workflow_service.get_workflow(db, session.workflow_id, company_id)
                            if workflow:
                                logging.info(f"[Messenger] Resuming paused workflow {workflow.id} from step {session.next_step_id}")
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

                                    await messaging_service.send_messenger_message(
                                        recipient_psid=sender_id,
                                        message_text=response_text,
                                        integration=integration
                                    )

                                    await session_ws_manager.broadcast_to_session(
                                        session.conversation_id,
                                        schemas_chat_message.ChatMessage.from_orm(db_agent_message).json(),
                                        "agent"
                                    )

                                elif execution_result.get("status") == "paused_for_prompt":
                                    # Send any intermediate response message first
                                    intermediate_response = execution_result.get("response")
                                    if intermediate_response:
                                        await messaging_service.send_messenger_message(
                                            recipient_psid=sender_id,
                                            message_text=intermediate_response,
                                            integration=integration
                                        )

                                    # Then send the prompt with formatted options
                                    prompt_data = execution_result.get("prompt", {})
                                    prompt_text = prompt_data.get("text", "Please choose an option:")
                                    options = prompt_data.get("options", [])

                                    # Format options as text for Messenger (no interactive buttons for simplicity)
                                    if options:
                                        if isinstance(options, str):
                                            option_list = [o.strip() for o in options.split(',')]
                                        elif isinstance(options, list):
                                            option_list = [o.get('label', o.get('value', str(o))) if isinstance(o, dict) else str(o) for o in options]
                                        else:
                                            option_list = []

                                        if option_list:
                                            prompt_text = f"{prompt_text}\n\nOptions:\n" + "\n".join([f"• {opt}" for opt in option_list])

                                    await messaging_service.send_messenger_message(
                                        recipient_psid=sender_id,
                                        message_text=prompt_text,
                                        integration=integration
                                    )

                                elif execution_result.get("status") in ["paused_for_input", "paused_for_form"]:
                                    # Send any response message first
                                    response_text = execution_result.get("response")
                                    if response_text:
                                        await messaging_service.send_messenger_message(
                                            recipient_psid=sender_id,
                                            message_text=response_text,
                                            integration=integration
                                        )

                                    # Also check for prompt text
                                    prompt_text = execution_result.get("prompt", {}).get("text")
                                    if prompt_text and prompt_text != response_text:
                                        await messaging_service.send_messenger_message(
                                            recipient_psid=sender_id,
                                            message_text=prompt_text,
                                            integration=integration
                                        )
                                    logging.info(f"[Messenger] Workflow paused for input in session {session.conversation_id}")

                                continue

                        # Priority: 1) Triggers, 2) LLM decision, 3) Similarity search

                        # 1. Try trigger-based workflow finding first
                        workflow = await workflow_trigger_service.find_workflow_for_channel_message(
                            db=db,
                            channel=TriggerChannel.MESSENGER,
                            company_id=company_id,
                            message=message_text,
                            session_data={"session_id": session.conversation_id}
                        )

                        if not workflow:
                            # 2. No trigger match - try LLM-based routing (2nd priority)
                            logging.info(f"[Messenger] No trigger match, trying LLM-based routing")
                            agents = agent_service.get_agents(db, company_id=company_id, limit=1)
                            if not agents:
                                logging.error(f"Error: No agents found for company {company_id} to handle the response.")
                                continue
                            agent = agents[0]

                            agent_response = await agent_execution_service.generate_agent_response(
                                db, agent.id, session.conversation_id, session.conversation_id, company_id, message_text
                            )

                            # Check if LLM decided to trigger a workflow (context-aware routing)
                            if isinstance(agent_response, dict) and agent_response.get("type") == "workflow_trigger":
                                workflow_id = agent_response.get("workflow_id")
                                logging.info(f"[Messenger] LLM triggered workflow {workflow_id}")
                                workflow = workflow_service.get_workflow(db, workflow_id, company_id)
                                if not workflow:
                                    logging.warning(f"[Messenger] Workflow {workflow_id} not found")
                                    continue
                                # Continue to workflow execution below
                            elif isinstance(agent_response, dict) and agent_response.get("type") == "handoff":
                                # LLM routing failed - notify user and initiate handoff
                                reason = agent_response.get("reason", "AI routing unavailable")
                                logging.warning(f"[Messenger] LLM failed, initiating handoff: {reason}")
                                error_msg = "I'm experiencing some technical difficulties. Let me connect you with a human agent who can help."
                                await messaging_service.send_messenger_message(
                                    recipient_psid=sender_id,
                                    message_text=error_msg,
                                    integration=integration
                                )
                                continue
                            else:
                                # 3. LLM returned text - try similarity search as last fallback
                                logging.info(f"[Messenger] LLM returned text, trying similarity search as fallback")
                                workflow = workflow_service.find_similar_workflow(db, company_id=company_id, query=message_text, agent_id=session.agent_id)

                                if not workflow:
                                    # No workflow found anywhere - use LLM's text response
                                    agent_response_text = agent_response if isinstance(agent_response, str) else str(agent_response)

                                    if not agent_response_text:
                                        logging.info(f"Agent did not generate a response for session {session.conversation_id}.")
                                        continue

                                    agent_message_schema = ChatMessageCreate(message=agent_response_text, message_type="text")
                                    db_agent_message = chat_service.create_chat_message(db, agent_message_schema, agent.id, session.conversation_id, company_id, "agent")

                                    await messaging_service.send_messenger_message(
                                        recipient_psid=sender_id,
                                        message_text=agent_response_text,
                                        integration=integration
                                    )

                                    await session_ws_manager.broadcast_to_session(
                                        session.conversation_id,
                                        schemas_chat_message.ChatMessage.from_orm(db_agent_message).json(),
                                        "agent"
                                    )
                                    continue

                        # --- Workflow Execution ---
                        # Get agent_id from workflow's agents (many-to-many) or use session's agent_id
                        workflow_agent_id = session.agent_id or (workflow.agents[0].id if workflow.agents else None)
                        # Update session with workflow's agent_id
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

                            await messaging_service.send_messenger_message(
                                recipient_psid=sender_id,
                                message_text=response_text,
                                integration=integration
                            )

                            await session_ws_manager.broadcast_to_session(
                                session.conversation_id,
                                schemas_chat_message.ChatMessage.from_orm(db_agent_message).json(),
                                "agent"
                            )

                        elif execution_result.get("status") == "paused_for_prompt":
                            # Send any intermediate response message first
                            intermediate_response = execution_result.get("response")
                            if intermediate_response:
                                await messaging_service.send_messenger_message(
                                    recipient_psid=sender_id,
                                    message_text=intermediate_response,
                                    integration=integration
                                )
                                logging.info(f"[Messenger] Sent intermediate response: {intermediate_response[:50]}...")

                            # Then send the prompt
                            prompt_data = execution_result.get("prompt", {})
                            prompt_text = prompt_data.get("text", "Please choose an option:")
                            options = prompt_data.get("options", [])

                            # Format options for text message
                            if options:
                                if isinstance(options, str):
                                    option_list = [o.strip() for o in options.split(',')]
                                elif isinstance(options, list):
                                    option_list = [o.get('label', o.get('value', str(o))) if isinstance(o, dict) else str(o) for o in options]
                                else:
                                    option_list = []

                                if option_list:
                                    prompt_text = f"{prompt_text}\n\nOptions:\n" + "\n".join([f"• {opt}" for opt in option_list])

                            await messaging_service.send_messenger_message(
                                recipient_psid=sender_id,
                                message_text=prompt_text,
                                integration=integration
                            )
                            logging.info(f"[Messenger] Sent prompt to user: {prompt_text[:50]}...")

                        elif execution_result.get("status") in ["paused_for_input", "paused_for_form"]:
                            prompt_text = execution_result.get("prompt", {}).get("text") or execution_result.get("response", "Please provide your input.")

                            await messaging_service.send_messenger_message(
                                recipient_psid=sender_id,
                                message_text=prompt_text,
                                integration=integration
                            )
                            logging.info(f"[Messenger] Sent input request to user: {prompt_text[:50]}...")

                        logging.info(f"Processed Messenger message from {sender_id} for company {company_id} with workflow '{workflow.name}'")

    except (KeyError, IndexError) as e:
        logging.error(f"Error parsing Messenger webhook data: {e}\n{traceback.format_exc()}")
    except Exception as e:
        logging.error(f"An unexpected error occurred: {e}\n{traceback.format_exc()}")

    return Response(status_code=200)
