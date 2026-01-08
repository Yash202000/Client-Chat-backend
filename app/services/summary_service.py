"""
Service for generating AI-powered conversation summaries.
Uses the session's default agent LLM or company's first agent as fallback.
"""

from sqlalchemy.orm import Session
from datetime import datetime
from typing import Optional

from app.models.conversation_session import ConversationSession
from app.models.agent import Agent
from app.models.chat_message import ChatMessage
from app.services import credential_service
from app.services import token_usage_service
from app.llm_providers import groq_provider, gemini_provider, openai_provider


PROVIDER_MAP = {
    "groq": groq_provider,
    "gemini": gemini_provider,
    "openai": openai_provider,
}

SUMMARIZATION_PROMPT = """Summarize this customer conversation concisely. Include:
- Main topic/issue discussed
- Key points raised by customer
- Resolution or current status
- Any action items or follow-ups needed

Keep the summary under 200 words. Be direct and factual.

Conversation:
{messages}"""


def _format_messages_for_summary(messages: list) -> str:
    """Format chat messages into a readable conversation format."""
    formatted = []
    for msg in messages:
        sender = "Customer" if msg.sender == "user" else "Agent"
        formatted.append(f"{sender}: {msg.message}")
    return "\n".join(formatted)


def _get_agent_for_summary(db: Session, session: ConversationSession, company_id: int) -> Optional[Agent]:
    """
    Get the agent to use for summary generation.
    Priority: session's agent > company's first agent
    """
    # First try session's agent
    if session.agent_id:
        agent = db.query(Agent).filter(
            Agent.id == session.agent_id,
            Agent.company_id == company_id
        ).first()
        if agent and agent.llm_provider:
            return agent

    # Fallback to company's first agent with LLM config
    return db.query(Agent).filter(
        Agent.company_id == company_id,
        Agent.llm_provider.isnot(None)
    ).first()


async def generate_conversation_summary(
    db: Session,
    session_id: str,
    company_id: int
) -> Optional[str]:
    """
    Generate an AI summary for a conversation session.

    Args:
        db: Database session
        session_id: The conversation session ID (conversation_id string)
        company_id: The company ID

    Returns:
        Generated summary text or None if generation failed
    """
    # Get the session
    session = db.query(ConversationSession).filter(
        ConversationSession.conversation_id == session_id,
        ConversationSession.company_id == company_id
    ).first()

    if not session:
        return None

    # Get messages for this session
    messages = db.query(ChatMessage).filter(
        ChatMessage.session_id == session.id,
        ChatMessage.message_type == "message"  # Exclude notes
    ).order_by(ChatMessage.timestamp.asc()).all()

    if not messages:
        return "No messages in this conversation."

    # Get agent for LLM config
    agent = _get_agent_for_summary(db, session, company_id)
    if not agent:
        raise ValueError("No agent with LLM configuration found for this company.")

    provider_module = PROVIDER_MAP.get(agent.llm_provider)
    if not provider_module:
        raise ValueError(f"LLM provider '{agent.llm_provider}' not supported.")

    # Get API key from vault
    api_key = None
    llm_credential = credential_service.get_credential_by_service_name(
        db, agent.llm_provider, company_id
    )
    if llm_credential:
        api_key = credential_service.get_decrypted_credential(
            db, llm_credential.id, company_id
        )

    # Format messages
    formatted_messages = _format_messages_for_summary(messages)

    # Build prompt
    system_prompt = SUMMARIZATION_PROMPT.format(messages=formatted_messages)

    # Call LLM
    try:
        response = await provider_module.generate_response(
            db=db,
            company_id=company_id,
            model_name=agent.model_name,
            system_prompt=system_prompt,
            chat_history=[],
            tools=None,
            api_key=api_key,
            stream=False
        )

        # Log token usage
        usage_data = response.get('usage')
        if usage_data:
            token_usage_service.log_token_usage(
                db=db,
                company_id=company_id,
                provider=agent.llm_provider,
                model_name=agent.model_name,
                prompt_tokens=usage_data.get('prompt_tokens', 0),
                completion_tokens=usage_data.get('completion_tokens', 0),
                agent_id=agent.id,
                session_id=session_id,
                request_type="summary"
            )

        summary = response.get('content', '')

        # Save summary to session
        session.summary = summary
        session.summary_generated_at = datetime.utcnow()
        db.commit()

        return summary

    except Exception as e:
        print(f"Error generating summary: {e}")
        raise


def get_session_summary(
    db: Session,
    session_id: str,
    company_id: int
) -> dict:
    """
    Get existing summary for a session.

    Returns:
        Dict with summary, generated_at, and exists flag
    """
    session = db.query(ConversationSession).filter(
        ConversationSession.conversation_id == session_id,
        ConversationSession.company_id == company_id
    ).first()

    if not session:
        return {"summary": None, "generated_at": None, "exists": False}

    return {
        "summary": session.summary,
        "generated_at": session.summary_generated_at,
        "exists": session.summary is not None
    }
