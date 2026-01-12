"""
Agent-to-agent handoff builtin tools implementation.
Handles transferring conversations between AI agents and consulting other agents.
"""
import traceback
import json
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.models.agent import Agent
from app.services import (
    conversation_session_service,
    agent_selection_service,
    chat_service,
    credential_service
)
from app.schemas.conversation_session import ConversationSessionUpdate
import logging

logger = logging.getLogger(__name__)


def _prepare_history_for_handoff(
    db: Session,
    session_id: str,
    company_id: int,
    history_mode: str,
    agent_id: int
) -> str:
    """
    Prepares conversation history based on the receiving agent's history_mode preference.

    Args:
        db: Database session
        session_id: Conversation session ID
        company_id: Company ID
        history_mode: "full", "summary", or "none"
        agent_id: Current agent ID

    Returns:
        Formatted history string or empty string
    """
    if history_mode == "none":
        return ""

    if history_mode == "summary":
        # Get session summary if available
        session = conversation_session_service.get_session(db, session_id)
        if session and session.summary:
            return f"Previous conversation summary: {session.summary}"

        # Fall back to generating a quick summary from recent messages
        messages = chat_service.get_chat_messages(db, agent_id, session_id, company_id, limit=10)
        if messages:
            summary_lines = []
            for msg in messages[-5:]:  # Last 5 messages
                role = "User" if msg.sender == "user" else "Agent"
                content = msg.message[:150] + "..." if len(msg.message) > 150 else msg.message
                summary_lines.append(f"{role}: {content}")
            return "Recent conversation:\n" + "\n".join(summary_lines)
        return ""

    # history_mode == "full"
    messages = chat_service.get_chat_messages(db, agent_id, session_id, company_id, limit=50)
    if not messages:
        return ""

    history_lines = []
    for msg in messages:
        role = "User" if msg.sender == "user" else "Agent"
        history_lines.append(f"{role}: {msg.message}")

    return "Full conversation history:\n" + "\n".join(history_lines)


async def execute_transfer_to_agent_tool(
    db: Session,
    session_id: str,
    company_id: int,
    parameters: dict
):
    """
    Executes the transfer_to_agent builtin tool.
    Transfers the conversation to another specialized AI agent.

    Args:
        db: Database session
        session_id: Conversation session ID
        company_id: Company ID
        parameters: Tool parameters (topic, reason, summary, target_agent_id)

    Returns:
        Dictionary with transfer result
    """
    topic = parameters.get("topic", "")
    reason = parameters.get("reason", "")
    summary = parameters.get("summary", "")
    target_agent_id = parameters.get("target_agent_id")

    logger.info(f"[TRANSFER TO AGENT] Session: {session_id}, Topic: {topic}, Reason: {reason}")

    try:
        # Get the current session
        session = conversation_session_service.get_session(db, session_id)
        if not session:
            logger.error(f"[TRANSFER TO AGENT] Session not found: {session_id}")
            return {"error": "Session not found"}

        current_agent_id = session.agent_id
        current_agent = db.query(Agent).filter(Agent.id == current_agent_id).first()

        # Find the target agent
        target_agent = None
        if target_agent_id:
            target_agent = agent_selection_service.get_agent_by_id_if_available(
                db, target_agent_id, company_id
            )

        if not target_agent:
            target_agent = agent_selection_service.find_agent_by_topic(
                db, topic, company_id, exclude_agent_id=current_agent_id
            )

        if not target_agent:
            logger.warning(f"[TRANSFER TO AGENT] No matching agent found for topic: {topic}")
            return {
                "result": {
                    "status": "no_agent_found",
                    "topic": topic,
                    "message": f"No specialized agent found for '{topic}'. Please try describing your need differently or I'll continue to assist you."
                }
            }

        # Get history based on target agent's preference
        history_mode = agent_selection_service.get_agent_history_mode(target_agent)
        conversation_history = _prepare_history_for_handoff(
            db, session_id, company_id, history_mode, current_agent_id
        )

        # Record the transition
        transition_history = session.agent_transition_history or []
        transition_history.append({
            "from_agent_id": current_agent_id,
            "from_agent_name": current_agent.name if current_agent else "Unknown",
            "to_agent_id": target_agent.id,
            "to_agent_name": target_agent.name,
            "type": "transfer",
            "topic": topic,
            "reason": reason,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })

        # Set original_agent_id if this is the first transfer
        original_agent_id = session.original_agent_id or current_agent_id

        # Update session with new agent
        session_update = ConversationSessionUpdate(
            agent_id=target_agent.id,
            original_agent_id=original_agent_id,
            previous_agent_id=current_agent_id,
            agent_transition_history=transition_history,
            handoff_summary=summary
        )

        conversation_session_service.update_session(db, session_id, session_update)

        # Broadcast agent transfer to frontend via WebSocket
        try:
            from app.services.connection_manager import manager
            transfer_message = json.dumps({
                "type": "agent_transfer",
                "session_id": session_id,
                "from_agent": {
                    "id": current_agent_id,
                    "name": current_agent.name if current_agent else "Unknown"
                },
                "to_agent": {
                    "id": target_agent.id,
                    "name": target_agent.name
                },
                "topic": topic,
                "reason": reason
            })
            await manager.broadcast_to_session(session_id, transfer_message, "system")
        except Exception as e:
            logger.warning(f"[TRANSFER TO AGENT] Failed to broadcast transfer event: {e}")

        # Get welcome message for the new agent
        welcome_message = agent_selection_service.get_agent_welcome_message(target_agent, topic)

        logger.info(f"[TRANSFER TO AGENT] Successfully transferred from agent {current_agent_id} to agent {target_agent.id} ({target_agent.name})")

        return {
            "result": {
                "status": "transferred",
                "from_agent_id": current_agent_id,
                "from_agent_name": current_agent.name if current_agent else "Unknown",
                "to_agent_id": target_agent.id,
                "to_agent_name": target_agent.name,
                "topic": topic,
                "conversation_history": conversation_history,
                "welcome_message": welcome_message,
                "history_mode": history_mode
            },
            "formatted_response": welcome_message
        }

    except Exception as e:
        logger.error(f"[TRANSFER TO AGENT] Error: {e}\n{traceback.format_exc()}")
        return {
            "error": "An error occurred during agent transfer.",
            "details": str(e)
        }


async def execute_consult_agent_tool(
    db: Session,
    session_id: str,
    company_id: int,
    parameters: dict
):
    """
    Executes the consult_agent builtin tool.
    Queries another agent for assistance without transferring the conversation.

    Args:
        db: Database session
        session_id: Conversation session ID
        company_id: Company ID
        parameters: Tool parameters (topic, question, context, target_agent_id)

    Returns:
        Dictionary with consultation result
    """
    topic = parameters.get("topic", "")
    question = parameters.get("question", "")
    context = parameters.get("context", "")
    target_agent_id = parameters.get("target_agent_id")

    logger.info(f"[CONSULT AGENT] Session: {session_id}, Topic: {topic}, Question: {question[:100]}...")

    try:
        # Get the current session
        session = conversation_session_service.get_session(db, session_id)
        if not session:
            logger.error(f"[CONSULT AGENT] Session not found: {session_id}")
            return {"error": "Session not found"}

        current_agent_id = session.agent_id

        # Find the consultant agent
        consultant_agent = None
        if target_agent_id:
            consultant_agent = agent_selection_service.get_agent_by_id_if_available(
                db, target_agent_id, company_id
            )

        if not consultant_agent:
            consultant_agent = agent_selection_service.find_agent_by_topic(
                db, topic, company_id, exclude_agent_id=current_agent_id
            )

        if not consultant_agent:
            logger.warning(f"[CONSULT AGENT] No matching agent found for topic: {topic}")
            return {
                "result": {
                    "status": "no_agent_found",
                    "topic": topic,
                    "message": f"No specialist agent found for '{topic}'. Unable to provide expert consultation."
                }
            }

        # Generate response from consultant agent using their LLM configuration
        from app.llm_providers import groq_provider, gemini_provider, openai_provider

        PROVIDER_MAP = {
            "groq": groq_provider,
            "gemini": gemini_provider,
            "openai": openai_provider,
        }

        provider_module = PROVIDER_MAP.get(consultant_agent.llm_provider)
        if not provider_module:
            logger.error(f"[CONSULT AGENT] LLM provider '{consultant_agent.llm_provider}' not supported")
            return {"error": f"LLM provider '{consultant_agent.llm_provider}' not supported for consultation"}

        # Build consultation prompt
        specializations_str = json.dumps(consultant_agent.specialization_topics or [], indent=2)
        consultation_prompt = f"""You are {consultant_agent.name}, a specialist AI agent.

Your areas of expertise:
{specializations_str}

Your personality: {consultant_agent.personality or 'helpful and professional'}
Your base instructions: {consultant_agent.prompt or 'Provide helpful and accurate information.'}

Another AI agent is consulting you for expert advice on a topic. Provide a helpful, concise, and accurate response based on your expertise.

Context from the conversation:
{context or 'No additional context provided.'}

Question being asked:
{question}

Provide your expert response (be concise and directly helpful):"""

        # Get API key for consultant agent
        consultant_api_key = None
        llm_credential = credential_service.get_credential_by_service_name(
            db, consultant_agent.llm_provider, company_id
        )
        if llm_credential:
            consultant_api_key = credential_service.get_decrypted_credential(
                db, llm_credential.id, company_id
            )

        # Generate consultation response
        consultation_response = await provider_module.generate_response(
            db=db,
            company_id=company_id,
            model_name=consultant_agent.model_name,
            system_prompt=consultation_prompt,
            chat_history=[{"role": "user", "content": question}],
            tools=None,
            api_key=consultant_api_key,
            stream=False
        )

        expert_response = consultation_response.get('content', 'Unable to generate consultation response.')

        # Record the consultation in transition history
        transition_history = session.agent_transition_history or []
        transition_history.append({
            "from_agent_id": current_agent_id,
            "to_agent_id": consultant_agent.id,
            "to_agent_name": consultant_agent.name,
            "type": "consult",
            "topic": topic,
            "question": question[:200] if len(question) > 200 else question,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })

        session_update = ConversationSessionUpdate(
            agent_transition_history=transition_history
        )
        conversation_session_service.update_session(db, session_id, session_update)

        logger.info(f"[CONSULT AGENT] Successfully consulted agent {consultant_agent.id} ({consultant_agent.name})")

        return {
            "result": {
                "status": "consultation_complete",
                "consultant_agent_id": consultant_agent.id,
                "consultant_agent_name": consultant_agent.name,
                "topic": topic,
                "question": question,
                "expert_response": expert_response
            }
        }

    except Exception as e:
        logger.error(f"[CONSULT AGENT] Error: {e}\n{traceback.format_exc()}")
        return {
            "error": "An error occurred during agent consultation.",
            "details": str(e)
        }
