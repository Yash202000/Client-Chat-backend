from sqlalchemy.orm import Session
from app.services import agent_service, chat_service, tool_service, tool_execution_service, workflow_execution_service, workflow_service, widget_settings_service
from app.core.config import settings
from app.models.chat_message import ChatMessage
from app.schemas.chat_message import ChatMessage as ChatMessageSchema
import json
from app.api.v1.endpoints.websocket_conversations import manager

# Import provider modules directly and create a provider map
from app.llm_providers import groq_provider, gemini_provider

PROVIDER_MAP = {
    "groq": groq_provider,
    "gemini": gemini_provider,
}

def format_chat_history(chat_messages: list) -> list[dict[str, str]]:
    """
    Formats the chat history from various possible types (SQLAlchemy models, dicts)
    into a standardized list of dictionaries with 'role' and 'content' keys.
    """
    history = []
    for msg in chat_messages:
        try:
            if hasattr(msg, 'sender') and hasattr(msg, 'message'):
                sender = msg.sender
                message = msg.message
            elif isinstance(msg, dict) and 'sender' in msg and 'message' in msg:
                sender = msg['sender']
                message = msg['message']
            else:
                continue

            role = "assistant" if sender == "agent" else sender
            history.append({"role": role, "content": message})
        except (AttributeError, TypeError) as e:
            print(f"Skipping malformed message in history: {msg}, error: {e}")
            continue
    return history


async def generate_agent_response(db: Session, agent_id: int, session_id: str, company_id: int, user_message: str):
    """
    Orchestrates the agent's response by dynamically loading the correct LLM provider,
    handling tool use, and generating a final reply.
    """
    agent = agent_service.get_agent(db, agent_id, company_id)
    if not agent:
        return "Error: Agent not found."

    # If no workflow is triggered, proceed with LLM-based tool selection or response generation
    provider_module = PROVIDER_MAP.get(agent.llm_provider)
    if not provider_module:
        return f"Error: LLM provider '{agent.llm_provider}' not found."

    # Correctly format tools, ensuring parameters is a dict
    generic_tools = [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters or {}
            }
        } for tool in agent.tools
    ]
    
    db_chat_history = chat_service.get_chat_messages(db, agent_id, session_id, company_id, limit=20)
    
    formatted_history = format_chat_history(db_chat_history)
    formatted_history.append({"role": "user", "content": user_message})

    # Check if typing indicator is enabled for this agent's widget
    widget_settings = widget_settings_service.get_widget_settings(db, agent_id)
    typing_indicator_enabled = widget_settings.typing_indicator_enabled if widget_settings else False

    if typing_indicator_enabled:
        await manager.broadcast_to_session(session_id, json.dumps({"type": "typing_on", "sender": "agent"}), "agent")

    try:
        agent_api_key = None
        if agent.credential and agent.credential.api_key:
            agent_api_key = agent.credential.api_key

        llm_response = provider_module.generate_response(
            db=db,
            company_id=company_id,
            model_name=agent.model_name,
            system_prompt=agent.prompt,
            chat_history=formatted_history,
            tools=generic_tools,
            api_key=agent_api_key # Pass agent-specific API key if available
        )
    except Exception as e:
        print(f"LLM Provider Error: {e}")
        if typing_indicator_enabled:
            await manager.broadcast_to_session(session_id, json.dumps({"type": "typing_off", "sender": "agent"}), "agent")
        return f"Error from LLM provider: {e}"

    if typing_indicator_enabled:
        await manager.broadcast_to_session(session_id, json.dumps({"type": "typing_off", "sender": "agent"}), "agent")

    if llm_response.get('type') == 'tool_call':
        tool_name = llm_response.get('tool_name')
        parameters = llm_response.get('parameters', {})
        
        db_tool = tool_service.get_tool_by_name(db, tool_name, company_id)
        if not db_tool:
            return f"Error: Tool '{tool_name}' not found."

        tool_result = tool_execution_service.execute_tool(
            db=db, tool_id=db_tool.id, company_id=company_id, session_id=session_id, parameters=parameters
        )
        
        result_content = tool_result.get('result', tool_result.get('error', 'No output'))
        return f"Tool '{tool_name}' executed. Result: {result_content}"
    
    elif llm_response.get('type') == 'text':
        return llm_response.get('content', 'No response content.')

    return "An unexpected error occurred."