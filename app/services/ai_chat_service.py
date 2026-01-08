import uuid
from sqlalchemy.orm import Session
from app.core.config import settings
from app.models import conversation_session as models_conversation_session, chat_message as models_chat_message
from app.schemas import ai_chat as schemas_ai_chat
from app.services import agent_execution_service
from app.services import token_usage_service
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
            contact_id=user_id, # Using user_id as contact_id for now
            channel="ai_chat",
            agent_id=chat_request.agent_id
        )
        db.add(session)
        db.commit()
        db.refresh(session)

    # 2. Save user message
    user_message = models_chat_message.ChatMessage(
        session_id=session.conversation_id,
        message=chat_request.message,
        sender='user',
        company_id=company_id,
        contact_id=user_id,
        agent_id=chat_request.agent_id
    )
    db.add(user_message)
    db.commit()
    db.refresh(user_message)

    # 3. Generate response
    if chat_request.agent_id:
        # Use the selected agent to generate a response
        await agent_execution_service.generate_agent_response(
            db=db,
            agent_id=chat_request.agent_id,
            session_id=session.conversation_id,
            company_id=company_id,
            user_message=chat_request.message
        )
        last_agent_message = db.query(models_chat_message.ChatMessage).filter(
            models_chat_message.ChatMessage.session_id == session.conversation_id,
            models_chat_message.ChatMessage.sender == 'agent'
        ).order_by(models_chat_message.ChatMessage.timestamp.desc()).first()
        return last_agent_message

    else:
        # Use default provider (Groq)
        history = db.query(models_chat_message.ChatMessage).filter(
            models_chat_message.ChatMessage.session_id == session.conversation_id
        ).order_by(models_chat_message.ChatMessage.timestamp.asc()).all()

        formatted_history = agent_execution_service.format_chat_history(history)

        system_prompt = "You are a helpful assistant."

        # Default to Groq, but can be changed to Gemini or other providers
        llm_response = await groq_provider.generate_response(
            db=db, company_id=company_id, model_name='llama-3.1-8b-instant',
            system_prompt=system_prompt, chat_history=formatted_history,
            tools=[], api_key=settings.GROQ_API_KEY
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
            session_id=session.conversation_id,
            message=response_text,
            sender='agent',
            company_id=company_id,
            contact_id=user_id
        )
        db.add(model_message)
        db.commit()
        db.refresh(model_message)

        return model_message
