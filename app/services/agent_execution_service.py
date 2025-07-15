from sqlalchemy.orm import Session
from app.services import agent_service, chat_service, tool_service, tool_execution_service
from app.core.config import settings
from app.models.chat_message import ChatMessage
from app.schemas.chat_message import ChatMessage as ChatMessageSchema
import json

# Import provider modules directly and create a provider map
from app.llm_providers import groq_provider, gemini_provider

PROVIDER_MAP = {
    "groq": groq_provider,
    "gemini": gemini_provider,
}

def get_api_key_for_agent(agent):
    """
    Gets the API key from the agent's credential, falling back to environment variables.
    """
    if agent.credential and agent.credential.api_key:
        return agent.credential.api_key
    
    if agent.llm_provider == 'groq':
        return settings.GROQ_API_KEY
    elif agent.llm_provider == 'gemini':
        return settings.GOOGLE_API_KEY
    return None

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

def generate_agent_response(db: Session, agent_id: int, session_id: str, company_id: int, user_message: str):
    """
    Orchestrates the agent's response by dynamically loading the correct LLM provider,
    handling tool use, and generating a final reply.
    """
    agent = agent_service.get_agent(db, agent_id, company_id)
    if not agent:
        return "Error: Agent not found."

    provider_module = PROVIDER_MAP.get(agent.llm_provider)
    if not provider_module:
        return f"Error: LLM provider '{agent.llm_provider}' not found."

    api_key = get_api_key_for_agent(agent)
    if not api_key:
        return f"Error: API key for {agent.llm_provider} not found."

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

    try:
        llm_response = provider_module.generate_response(
            api_key=api_key,
            model_name=agent.model_name,
            system_prompt=agent.prompt,
            chat_history=formatted_history,
            tools=generic_tools
        )
    except Exception as e:
        print(f"LLM Provider Error: {e}")
        return f"Error from LLM provider: {e}"

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