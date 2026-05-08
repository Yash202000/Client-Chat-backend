import uuid
from sqlalchemy.orm import Session
from app.core.config import settings
from app.models import conversation_session as models_conversation_session, chat_message as models_chat_message
from app.schemas import ai_chat as schemas_ai_chat
from app.services import agent_execution_service
from app.services import token_usage_service
from app.services import chat_service
from app.schemas import chat_message as schemas_chat_message
from app.llm_providers import groq_provider, gemini_provider

async def handle_ai_chat(db: Session, chat_request: schemas_ai_chat.AIChatRequest, company_id: int, user_id: int):
    # 1. Get or create conversation session
    if chat_request.conversation_id:
        session = db.query(models_conversation_session.ConversationSession).filter(
            models_conversation_session.ConversationSession.conversation_id == chat_request.conversation_id
        ).first()
    else:
        conversation_id = str(uuid.uuid4())
        session = models_conversation_session.ConversationSession(
            conversation_id=conversation_id,
            company_id=company_id,
            contact_id=None,
            channel="ai_chat",
            agent_id=chat_request.agent_id
        )
        db.add(session)
        db.commit()
        db.refresh(session)

    # 2. Save user message
    user_message = models_chat_message.ChatMessage(
        session_id=session.id,  # Use session.id (integer PK), not conversation_id (UUID string)
        message=chat_request.message,
        sender='user',
        company_id=company_id,
        contact_id=None,
        agent_id=chat_request.agent_id
    )
    db.add(user_message)
    db.commit()
    db.refresh(user_message)

    # 3. Generate response
    if chat_request.agent_id:
        # If option_key is provided (user selected a prompt option), use it as the effective message
        effective_message = chat_request.option_key if chat_request.option_key else chat_request.message
        # generate_agent_response returns the text; saving to DB is the caller's responsibility
        _trace: dict = {}
        response = await agent_execution_service.generate_agent_response(
            db=db,
            agent_id=chat_request.agent_id,
            session_id=session.conversation_id,
            boradcast_session_id=session.conversation_id,
            company_id=company_id,
            user_message=effective_message,
            _trace=_trace,
        )
        # Extract plain text from response (may be str or dict with "text" key)
        if isinstance(response, dict):
            response_text = response.get("text") or ""
        else:
            response_text = str(response) if response else ""

        # Determine message_type and options from response
        options = None
        message_type = "message"
        if isinstance(response, dict) and response.get("options"):
            options = response["options"]
            message_type = "prompt"

        # Build ordered cascade execution steps for frontend animation
        final_status = "success" if response_text else "error"
        from app.services import agent_service
        agent_obj = agent_service.get_agent(db, chat_request.agent_id, company_id)

        tool_name_used = _trace.get('tool_name')
        workflow_id_used = _trace.get('workflow_id')
        if isinstance(response, dict) and response.get('type') == 'workflow_trigger':
            workflow_id_used = response.get('workflow_id')
        kb_used = _trace.get('kb_used', False)

        middle_steps = []
        if agent_obj:
            if kb_used:
                for kb in (agent_obj.knowledge_bases or []):
                    middle_steps.append({"node_id": f"knowledge-{kb.id}", "status": final_status})
            if tool_name_used:
                for tool in (agent_obj.tools or []):
                    if tool.name == tool_name_used:
                        middle_steps.append({"node_id": f"tools-{tool.id}", "status": final_status})
                        break
            if workflow_id_used:
                middle_steps.append({"node_id": f"workflow-{workflow_id_used}", "status": final_status})

        # Cascade order: chat-message → agent → [kb/tool/wf] → agent → chat-message
        if middle_steps:
            execution_steps = [
                {"node_id": "chat-message-node", "status": "success"},
                {"node_id": "agent-node", "status": "success"},
                *middle_steps,
                {"node_id": "agent-node", "status": final_status},
                {"node_id": "chat-message-node", "status": final_status},
            ]
        else:
            execution_steps = [
                {"node_id": "chat-message-node", "status": "success"},
                {"node_id": "agent-node", "status": final_status},
                {"node_id": "chat-message-node", "status": final_status},
            ]

        # Save the agent response to DB
        msg_create = schemas_chat_message.ChatMessageCreate(
            message=response_text,
            message_type=message_type,
        )
        db_message = chat_service.create_chat_message(
            db=db,
            message=msg_create,
            agent_id=chat_request.agent_id,
            session_id=session.conversation_id,
            company_id=company_id,
            sender="agent",
            options=options,
        )
        db_message.conversation_id = session.conversation_id
        db_message.execution_steps = execution_steps
        return db_message

    else:
        # Use default provider (Groq)
        history = db.query(models_chat_message.ChatMessage).filter(
            models_chat_message.ChatMessage.session_id == session.id
        ).order_by(models_chat_message.ChatMessage.timestamp.asc()).all()

        formatted_history = agent_execution_service.format_chat_history(history)

        system_prompt = "You are a helpful assistant."

        # Default to Groq, but can be changed to Gemini or other providers
        llm_response = await groq_provider.generate_response(
            db=db, company_id=company_id, model_name='llama-3.1-8b-instant',
            system_prompt=system_prompt, chat_history=formatted_history,
            tools=[], api_key=settings.GROQ_API_KEY, stream=False
        )

        # Log token usage
        usage_data = llm_response.get('usage') if isinstance(llm_response, dict) else None
        if usage_data:
            token_usage_service.log_token_usage(
                db=db,
                company_id=company_id,
                provider="groq",
                model_name="llama-3.1-8b-instant",
                prompt_tokens=usage_data.get('prompt_tokens', 0),
                completion_tokens=usage_data.get('completion_tokens', 0),
                session_id=session.conversation_id,
                request_type="chat"
            )

        response_text = llm_response.get('content', 'No response content.')

        model_message = models_chat_message.ChatMessage(
            session_id=session.id,  # Use session.id (integer PK), not conversation_id (UUID string)
            message=response_text,
            sender='agent',
            company_id=company_id,
            contact_id=None
        )
        db.add(model_message)
        db.commit()
        db.refresh(model_message)

        model_message.conversation_id = session.conversation_id
        return model_message
