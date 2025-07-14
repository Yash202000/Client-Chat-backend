from sqlalchemy.orm import Session
from app.services import agent_service, chat_service, tool_service, tool_execution_service
from app.core.config import settings

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
    
    # Fallback to environment variables
    if agent.llm_provider == 'groq':
        return settings.GROQ_API_KEY
    elif agent.llm_provider == 'gemini':
        return settings.GOOGLE_API_KEY
    return None


def generate_agent_response(db: Session, agent_id: int, session_id: str, company_id: int, user_message: str):
    """
    Orchestrates the agent's response by dynamically loading the correct LLM provider,
    handling tool use, and generating a final reply.
    """
    # 1. Fetch Agent with its credentials
    agent = agent_service.get_agent(db, agent_id, company_id)
    if not agent:
        return "Error: Agent not found."

    # 2. Get the appropriate provider from the map
    provider_module = PROVIDER_MAP.get(agent.llm_provider)
    if not provider_module:
        return f"Error: LLM provider '{agent.llm_provider}' not found or not supported."

    # 3. Get the API key from the vault or settings
    api_key = get_api_key_for_agent(agent)
    if not api_key:
        return f"Error: API key for {agent.llm_provider} not found in credentials or environment variables."

    # 4. Format tools and history
    generic_tools = [{"name": tool.name, "description": tool.description, "parameters": tool.parameters} for tool in agent.tools]
    chat_history = chat_service.get_chat_messages(db, agent_id, session_id, company_id, limit=20)
    chat_history.append(type('obj', (object,), {'sender': 'user', 'message': user_message})())

    # 5. Call the selected provider
    try:
        llm_response = provider_module.generate_response(
            api_key=api_key,
            model_name=agent.model_name,
            system_prompt=agent.prompt,
            chat_history=chat_history,
            tools=generic_tools
        )
    except Exception as e:
        return f"Error from LLM provider: {e}"

    # 6. Process the response
    if llm_response['type'] == 'tool_call':
        tool_name = llm_response['tool_name']
        parameters = llm_response['parameters']
        
        db_tool = tool_service.get_tool_by_name(db, tool_name, company_id)
        if not db_tool:
            return f"Error: The model tried to use a tool named '{tool_name}' which was not found."

        tool_result = tool_execution_service.execute_tool(
            db=db, tool_id=db_tool.id, company_id=company_id, session_id=session_id, parameters=parameters
        )
        
        return f"Tool '{tool_name}' executed. Result: {tool_result.get('result', tool_result.get('error', 'No output'))}"
    
    elif llm_response['type'] == 'text':
        return llm_response['content']

    return "An unexpected error occurred."
