"""
API Channel Service

Handles message processing for the API channel, following the same patterns
as WhatsApp, Telegram, and other channel handlers.
"""
import hashlib
import hmac
import httpx
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

from sqlalchemy.orm import Session

from app.models.api_integration import ApiIntegration
from app.models.conversation_session import ConversationSession
from app.models.api_key import ApiKey
from app.models.workflow_trigger import TriggerChannel
from app.schemas.api_channel import (
    ApiMessageSend, ApiMessageResponse, ResponseMode,
    ApiMessageItem, ApiMessageList
)
from app.schemas.chat_message import ChatMessageCreate
from app.services import (
    conversation_session_service,
    chat_service,
    workflow_service,
    workflow_trigger_service,
    agent_service,
    agent_execution_service,
    contact_service
)
from app.services.workflow_execution_service import WorkflowExecutionService
from app.api.v1.endpoints.websocket_conversations import manager as session_ws_manager
from app.schemas import chat_message as schemas_chat_message

logger = logging.getLogger(__name__)


class ApiChannelService:
    """Service for processing API channel messages."""

    def __init__(self, db: Session):
        self.db = db

    async def process_message(
        self,
        message_data: ApiMessageSend,
        api_integration: ApiIntegration,
        company_id: int
    ) -> ApiMessageResponse:
        """
        Process an incoming message from the API channel.

        This follows the same pattern as WhatsApp/Telegram handlers:
        1. Get or create contact
        2. Get or create session
        3. Save user message
        4. Execute workflow or agent
        5. Save and return response
        """
        # 1. Get or create contact for this external user
        contact = contact_service.get_or_create_contact_for_channel(
            self.db,
            company_id=company_id,
            channel='api',
            channel_identifier=message_data.external_user_id,
            name=message_data.metadata.get('user_name') if message_data.metadata else None
        )

        # 2. Get or create session
        session = self._get_or_create_session(
            message_data=message_data,
            contact_id=contact.id,
            company_id=company_id,
            api_integration=api_integration
        )

        # 3. Handle restart commands
        if conversation_session_service.is_restart_command(message_data.message):
            return await self._handle_restart(session, company_id, message_data)

        # 4. Reopen if resolved
        if session.status == 'resolved':
            session = await conversation_session_service.reopen_resolved_session(
                self.db, session, company_id
            )
            logger.info(f"Reopened resolved session {session.conversation_id}")

        # 5. Apply additional context if provided
        if message_data.context:
            current_context = session.context or {}
            current_context.update(message_data.context)
            session.context = current_context
            self.db.commit()

        # 6. Save user message
        chat_message = ChatMessageCreate(
            message=message_data.message,
            message_type=message_data.message_type
        )
        user_db_message = chat_service.create_chat_message(
            self.db,
            chat_message,
            agent_id=None,
            session_id=session.conversation_id,
            company_id=company_id,
            sender="user",
            attachments=message_data.attachments
        )

        # Broadcast to WebSocket (for dashboard visibility)
        try:
            await session_ws_manager.broadcast_to_session(
                session.conversation_id,
                schemas_chat_message.ChatMessage.model_validate(user_db_message, from_attributes=True).model_dump_json(),
                "user"
            )
        except Exception as e:
            logger.warning(f"Failed to broadcast to WebSocket: {e}")

        # 7. Check AI enabled
        if not session.is_ai_enabled:
            logger.info(f"AI is disabled for session {session.conversation_id}")
            return ApiMessageResponse(
                session_id=session.conversation_id,
                message_id=user_db_message.id,
                status="pending",
                response_message=None,
                metadata=message_data.metadata,
                created_at=datetime.now(timezone.utc)
            )

        # 8. Execute workflow or agent
        response = await self._execute_response(
            session=session,
            message_text=message_data.message,
            company_id=company_id,
            api_integration=api_integration,
            message_data=message_data,
            user_message_id=user_db_message.id
        )

        # 9. Handle async response mode (webhook callback)
        if message_data.response_mode == ResponseMode.ASYNC:
            if api_integration.webhook_enabled and api_integration.webhook_url:
                await self._send_webhook_callback(
                    api_integration=api_integration,
                    session=session,
                    response=response,
                    external_user_id=message_data.external_user_id
                )

        return response

    def _get_or_create_session(
        self,
        message_data: ApiMessageSend,
        contact_id: int,
        company_id: int,
        api_integration: ApiIntegration
    ) -> ConversationSession:
        """Get existing session or create new one."""
        # Generate session ID based on external_user_id
        conversation_id = f"api_{company_id}_{message_data.external_user_id}"

        # Determine workflow/agent
        workflow_id = message_data.workflow_id or api_integration.default_workflow_id
        agent_id = message_data.agent_id or api_integration.default_agent_id

        return conversation_session_service.get_or_create_session(
            self.db,
            conversation_id=conversation_id,
            workflow_id=workflow_id,
            contact_id=contact_id,
            channel='api',
            company_id=company_id,
            agent_id=agent_id
        )

    async def _execute_response(
        self,
        session: ConversationSession,
        message_text: str,
        company_id: int,
        api_integration: ApiIntegration,
        message_data: ApiMessageSend,
        user_message_id: int
    ) -> ApiMessageResponse:
        """Execute workflow or agent and return response."""

        # Check if workflow is paused and waiting for input
        if session.next_step_id and session.workflow_id:
            workflow = workflow_service.get_workflow(self.db, session.workflow_id, company_id)
            if workflow:
                logger.info(f"Resuming paused workflow {workflow.id} from step {session.next_step_id}")
                return await self._resume_workflow(
                    session, workflow, message_text, company_id, message_data, user_message_id
                )

        # Priority: 1) Triggers, 2) LLM decision, 3) Similarity search

        # 1. Find matching workflow via triggers
        workflow = await workflow_trigger_service.find_workflow_for_channel_message(
            db=self.db,
            channel=TriggerChannel.API,
            company_id=company_id,
            message=message_text,
            session_data={"session_id": session.conversation_id}
        )

        if workflow:
            return await self._execute_workflow(
                session, workflow, message_text, company_id, message_data, user_message_id
            )

        # 2. No trigger match - try LLM-based routing
        agent_id = api_integration.default_agent_id
        if not agent_id:
            agents = agent_service.get_agents(self.db, company_id=company_id, limit=1)
            if agents:
                agent_id = agents[0].id

        if agent_id:
            response = await agent_execution_service.generate_agent_response(
                self.db, agent_id, session.conversation_id,
                session.conversation_id, company_id, message_text
            )

            # Check if LLM decided to trigger a workflow (context-aware routing)
            if isinstance(response, dict) and response.get("type") == "workflow_trigger":
                workflow_id = response.get("workflow_id")
                workflow = workflow_service.get_workflow(self.db, workflow_id, company_id)
                if workflow:
                    logger.info(f"[API] LLM triggered workflow {workflow_id}")
                    return await self._execute_workflow(
                        session, workflow, message_text, company_id, message_data, user_message_id
                    )

            # Handle handoff request
            if isinstance(response, dict) and response.get("type") == "handoff":
                return ApiMessageResponse(
                    session_id=session.conversation_id,
                    message_id=user_message_id,
                    response_message="I'm connecting you with a human agent who can help.",
                    response_type="handoff",
                    status="handoff_requested",
                    metadata=message_data.metadata,
                    created_at=datetime.now(timezone.utc)
                )

            # 3. LLM returned text - try similarity search as last fallback
            workflow = workflow_service.find_similar_workflow(
                self.db, company_id=company_id, query=message_text, agent_id=session.agent_id
            )

            if workflow:
                logger.info(f"[API] Found similar workflow via fallback: {workflow.name}")
                return await self._execute_workflow(
                    session, workflow, message_text, company_id, message_data, user_message_id
                )

            # No workflow found - use LLM's text response
            response_text = response if isinstance(response, str) else str(response)
            agent_message = ChatMessageCreate(message=response_text, message_type="text")
            db_message = chat_service.create_chat_message(
                self.db, agent_message, agent_id,
                session.conversation_id, company_id, "agent"
            )

            # Broadcast to WebSocket
            try:
                await session_ws_manager.broadcast_to_session(
                    session.conversation_id,
                    schemas_chat_message.ChatMessage.model_validate(db_message, from_attributes=True).model_dump_json(),
                    "agent"
                )
            except Exception as e:
                logger.warning(f"Failed to broadcast to WebSocket: {e}")

            return ApiMessageResponse(
                session_id=session.conversation_id,
                message_id=db_message.id,
                response_message=response_text,
                response_type="text",
                status="completed",
                metadata=message_data.metadata,
                created_at=datetime.now(timezone.utc)
            )

        # No agent available
        return ApiMessageResponse(
            session_id=session.conversation_id,
            message_id=user_message_id,
            response_message="No agent available to handle this request.",
            response_type="error",
            status="error",
            metadata=message_data.metadata,
            created_at=datetime.now(timezone.utc)
        )

    async def _execute_workflow(
        self,
        session: ConversationSession,
        workflow,
        message_text: str,
        company_id: int,
        message_data: ApiMessageSend,
        user_message_id: int
    ) -> ApiMessageResponse:
        """Execute a workflow and return response."""
        # Get agent_id from workflow's agents (many-to-many) or use session's agent_id
        workflow_agent_id = session.agent_id or (workflow.agents[0].id if workflow.agents else None)

        # Update session with workflow's agent_id if needed
        if workflow_agent_id and session.agent_id != workflow_agent_id:
            session.agent_id = workflow_agent_id
            self.db.commit()
            self.db.refresh(session)

        workflow_exec_service = WorkflowExecutionService(self.db)
        result = await workflow_exec_service.execute_workflow(
            workflow_id=workflow.id,
            user_message=message_text,
            conversation_id=session.conversation_id,
            company_id=company_id,
            attachments=message_data.attachments,
            agent_id=workflow_agent_id
        )

        return await self._build_response_from_workflow_result(
            result, session, company_id, workflow_agent_id, message_data, user_message_id
        )

    async def _resume_workflow(
        self,
        session: ConversationSession,
        workflow,
        message_text: str,
        company_id: int,
        message_data: ApiMessageSend,
        user_message_id: int
    ) -> ApiMessageResponse:
        """Resume a paused workflow."""
        # Get agent_id from workflow's agents (many-to-many) or use session's agent_id
        workflow_agent_id = session.agent_id or (workflow.agents[0].id if workflow.agents else None)

        workflow_exec_service = WorkflowExecutionService(self.db)
        result = await workflow_exec_service.execute_workflow(
            user_message=message_text,
            conversation_id=session.conversation_id,
            company_id=company_id,
            workflow=workflow,
            attachments=message_data.attachments,
            agent_id=workflow_agent_id
        )

        return await self._build_response_from_workflow_result(
            result, session, company_id, workflow_agent_id, message_data, user_message_id
        )

    async def _build_response_from_workflow_result(
        self,
        result: Dict[str, Any],
        session: ConversationSession,
        company_id: int,
        agent_id: int,
        message_data: ApiMessageSend,
        user_message_id: int
    ) -> ApiMessageResponse:
        """Build API response from workflow execution result."""
        status = result.get("status", "completed")

        # Get preceding response message (sent before prompt/input pause)
        preceding_response = result.get("response")
        preceding_messages = None
        if preceding_response:
            if isinstance(preceding_response, list):
                preceding_messages = [str(m) for m in preceding_response]
            elif isinstance(preceding_response, str) and preceding_response:
                preceding_messages = [preceding_response]

        if status == "completed":
            response_text = result.get("response", "")
            # Handle if response is a list (take last one as main response)
            if isinstance(response_text, list) and response_text:
                response_text = str(response_text[-1])

            # Save agent message
            agent_message = ChatMessageCreate(message=response_text, message_type="text")
            db_message = chat_service.create_chat_message(
                self.db, agent_message, agent_id,
                session.conversation_id, company_id, "agent"
            )

            # Broadcast to WebSocket
            try:
                await session_ws_manager.broadcast_to_session(
                    session.conversation_id,
                    schemas_chat_message.ChatMessage.model_validate(db_message, from_attributes=True).model_dump_json(),
                    "agent"
                )
            except Exception as e:
                logger.warning(f"Failed to broadcast to WebSocket: {e}")

            return ApiMessageResponse(
                session_id=session.conversation_id,
                message_id=db_message.id,
                response_message=response_text,
                response_type="text",
                status="completed",
                workflow_status="completed",
                metadata=message_data.metadata,
                created_at=datetime.now(timezone.utc)
            )

        elif status == "paused_for_prompt":
            prompt = result.get("prompt", {})
            prompt_text = prompt.get("text", "Please choose an option:")
            options = prompt.get("options", [])

            # Build options_text for human-readable display
            options_text = None
            if options:
                if isinstance(options, list):
                    # Handle list of dicts with key/value or simple strings
                    option_labels = []
                    for opt in options:
                        if isinstance(opt, dict):
                            option_labels.append(opt.get("value") or opt.get("key") or str(opt))
                        else:
                            option_labels.append(str(opt))
                    options_text = ", ".join(option_labels)

            # Combine preceding messages with prompt for better context
            combined_message = prompt_text
            if preceding_messages:
                combined_message = "\n\n".join(preceding_messages + [prompt_text])

            # Save prompt message
            prompt_message = ChatMessageCreate(message=prompt_text, message_type="prompt")
            db_message = chat_service.create_chat_message(
                self.db, prompt_message, agent_id,
                session.conversation_id, company_id, "agent",
                options=options
            )

            # Broadcast to WebSocket
            try:
                await session_ws_manager.broadcast_to_session(
                    session.conversation_id,
                    schemas_chat_message.ChatMessage.model_validate(db_message, from_attributes=True).model_dump_json(),
                    "agent"
                )
            except Exception as e:
                logger.warning(f"Failed to broadcast to WebSocket: {e}")

            return ApiMessageResponse(
                session_id=session.conversation_id,
                message_id=db_message.id,
                response_message=combined_message,
                response_type="prompt",
                options=options,
                options_text=options_text,
                preceding_messages=preceding_messages,
                status="paused_for_prompt",
                workflow_status="paused_for_prompt",
                metadata=message_data.metadata,
                created_at=datetime.now(timezone.utc)
            )

        elif status == "paused_for_input":
            prompt = result.get("prompt", {})
            prompt_text = prompt.get("text", "Please provide input:")

            if prompt_text:
                # Save input request message
                input_message = ChatMessageCreate(message=prompt_text, message_type="text")
                db_message = chat_service.create_chat_message(
                    self.db, input_message, agent_id,
                    session.conversation_id, company_id, "agent"
                )

                # Broadcast to WebSocket
                try:
                    await session_ws_manager.broadcast_to_session(
                        session.conversation_id,
                        schemas_chat_message.ChatMessage.model_validate(db_message, from_attributes=True).model_dump_json(),
                        "agent"
                    )
                except Exception as e:
                    logger.warning(f"Failed to broadcast to WebSocket: {e}")

                return ApiMessageResponse(
                    session_id=session.conversation_id,
                    message_id=db_message.id,
                    response_message=prompt_text,
                    response_type="input",
                    status="paused_for_input",
                    workflow_status="paused_for_input",
                    metadata=message_data.metadata,
                    created_at=datetime.now(timezone.utc)
                )

            return ApiMessageResponse(
                session_id=session.conversation_id,
                message_id=user_message_id,
                status="paused_for_input",
                workflow_status="paused_for_input",
                metadata=message_data.metadata,
                created_at=datetime.now(timezone.utc)
            )

        # Default/unknown status
        return ApiMessageResponse(
            session_id=session.conversation_id,
            message_id=user_message_id,
            status=status,
            workflow_status=status,
            metadata=message_data.metadata,
            created_at=datetime.now(timezone.utc)
        )

    async def _execute_agent_response(
        self,
        session: ConversationSession,
        message_text: str,
        company_id: int,
        api_integration: ApiIntegration,
        message_data: ApiMessageSend,
        user_message_id: int
    ) -> ApiMessageResponse:
        """Execute agent response when no workflow matches."""
        agent_id = api_integration.default_agent_id

        if not agent_id:
            agents = agent_service.get_agents(self.db, company_id=company_id, limit=1)
            if not agents:
                logger.warning(f"No agents found for company {company_id}")
                return ApiMessageResponse(
                    session_id=session.conversation_id,
                    message_id=user_message_id,
                    response_message="No agent available to handle this request.",
                    response_type="error",
                    status="error",
                    metadata=message_data.metadata,
                    created_at=datetime.now(timezone.utc)
                )
            agent_id = agents[0].id

        response = await agent_execution_service.generate_agent_response(
            self.db, agent_id, session.conversation_id,
            session.conversation_id, company_id, message_text
        )

        # Handle workflow trigger from agent
        if isinstance(response, dict) and response.get("type") == "workflow_trigger":
            workflow_id = response.get("workflow_id")
            workflow = workflow_service.get_workflow(self.db, workflow_id, company_id)
            if workflow:
                logger.info(f"Agent triggered workflow {workflow_id}")
                return await self._execute_workflow(
                    session, workflow, message_text, company_id, message_data, user_message_id
                )

        # Handle handoff request
        if isinstance(response, dict) and response.get("type") == "handoff":
            reason = response.get("reason", "Handoff requested")
            return ApiMessageResponse(
                session_id=session.conversation_id,
                message_id=user_message_id,
                response_message="I'm connecting you with a human agent who can help.",
                response_type="handoff",
                status="handoff_requested",
                metadata=message_data.metadata,
                created_at=datetime.now(timezone.utc)
            )

        # Regular response
        response_text = response if isinstance(response, str) else str(response)

        agent_message = ChatMessageCreate(message=response_text, message_type="text")
        db_message = chat_service.create_chat_message(
            self.db, agent_message, agent_id,
            session.conversation_id, company_id, "agent"
        )

        # Broadcast to WebSocket
        try:
            await session_ws_manager.broadcast_to_session(
                session.conversation_id,
                schemas_chat_message.ChatMessage.model_validate(db_message, from_attributes=True).model_dump_json(),
                "agent"
            )
        except Exception as e:
            logger.warning(f"Failed to broadcast to WebSocket: {e}")

        return ApiMessageResponse(
            session_id=session.conversation_id,
            message_id=db_message.id,
            response_message=response_text,
            response_type="text",
            status="completed",
            metadata=message_data.metadata,
            created_at=datetime.now(timezone.utc)
        )

    async def _handle_restart(
        self,
        session: ConversationSession,
        company_id: int,
        message_data: ApiMessageSend
    ) -> ApiMessageResponse:
        """Handle conversation restart."""
        logger.info(f"Restart command received for session {session.conversation_id}")

        await conversation_session_service.reset_session_workflow(
            self.db, session, company_id
        )

        confirmation = "Conversation restarted. How can I help you?"

        # Save user message
        user_msg = ChatMessageCreate(message=message_data.message, message_type="text")
        user_db_message = chat_service.create_chat_message(
            self.db, user_msg, None, session.conversation_id, company_id, "user"
        )

        # Save confirmation
        agent_msg = ChatMessageCreate(message=confirmation, message_type="text")
        db_message = chat_service.create_chat_message(
            self.db, agent_msg, None, session.conversation_id, company_id, "agent"
        )

        # Broadcast to WebSocket
        try:
            await session_ws_manager.broadcast_to_session(
                session.conversation_id,
                schemas_chat_message.ChatMessage.model_validate(user_db_message, from_attributes=True).model_dump_json(),
                "user"
            )
            await session_ws_manager.broadcast_to_session(
                session.conversation_id,
                schemas_chat_message.ChatMessage.model_validate(db_message, from_attributes=True).model_dump_json(),
                "agent"
            )
        except Exception as e:
            logger.warning(f"Failed to broadcast to WebSocket: {e}")

        return ApiMessageResponse(
            session_id=session.conversation_id,
            message_id=db_message.id,
            response_message=confirmation,
            response_type="text",
            status="completed",
            metadata=message_data.metadata,
            created_at=datetime.now(timezone.utc)
        )

    async def _send_webhook_callback(
        self,
        api_integration: ApiIntegration,
        session: ConversationSession,
        response: ApiMessageResponse,
        external_user_id: str
    ):
        """Send async response to webhook URL."""
        payload = {
            "event_type": "message_response",
            "session_id": session.conversation_id,
            "external_user_id": external_user_id,
            "message_id": response.message_id,
            "message": response.response_message,
            "message_type": response.response_type,
            "options": response.options,
            "attachments": response.attachments,
            "status": response.status,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "metadata": response.metadata
        }

        # Generate HMAC signature
        payload_json = str(payload)
        signature = hmac.new(
            (api_integration.webhook_secret or "").encode(),
            payload_json.encode(),
            hashlib.sha256
        ).hexdigest()

        payload["signature"] = signature

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                await client.post(
                    api_integration.webhook_url,
                    json=payload,
                    headers={
                        "Content-Type": "application/json",
                        "X-Webhook-Signature": signature
                    }
                )
                logger.info(f"Webhook callback sent to {api_integration.webhook_url}")
        except Exception as e:
            logger.error(f"Webhook callback failed: {e}")


# ============ Helper Functions ============

def get_api_integration_by_api_key(
    db: Session, api_key: ApiKey
) -> Optional[ApiIntegration]:
    """Get API integration linked to an API key."""
    return db.query(ApiIntegration).filter(
        ApiIntegration.api_key_id == api_key.id,
        ApiIntegration.is_active == True
    ).first()


def get_api_integration(
    db: Session, integration_id: int, company_id: int
) -> Optional[ApiIntegration]:
    """Get API integration by ID."""
    return db.query(ApiIntegration).filter(
        ApiIntegration.id == integration_id,
        ApiIntegration.company_id == company_id
    ).first()


def get_api_integrations_by_company(
    db: Session, company_id: int
) -> List[ApiIntegration]:
    """Get all API integrations for a company."""
    return db.query(ApiIntegration).filter(
        ApiIntegration.company_id == company_id
    ).all()


def create_api_integration(
    db: Session,
    api_key_id: int,
    company_id: int,
    data: dict
) -> ApiIntegration:
    """Create a new API integration."""
    integration = ApiIntegration(
        api_key_id=api_key_id,
        company_id=company_id,
        **data
    )
    db.add(integration)
    db.commit()
    db.refresh(integration)
    return integration


def update_api_integration(
    db: Session,
    integration: ApiIntegration,
    data: dict
) -> ApiIntegration:
    """Update an API integration."""
    for key, value in data.items():
        if value is not None:
            setattr(integration, key, value)
    db.commit()
    db.refresh(integration)
    return integration


def delete_api_integration(
    db: Session,
    integration: ApiIntegration
) -> None:
    """Delete an API integration."""
    db.delete(integration)
    db.commit()
