from sqlalchemy.orm import Session
from app.services import agent_service, chat_service, tool_service, tool_execution_service, workflow_execution_service, workflow_service, widget_settings_service
from app.core.config import settings
from app.models.chat_message import ChatMessage
from app.schemas.chat_message import ChatMessage as ChatMessageSchema, ChatMessageCreate
import json
from app.core.websockets import manager
from app.services.vault_service import vault_service

class CustomJsonEncoder(json.JSONEncoder):
    def default(self, o):
        if hasattr(o, 'result'):
             return o.result
        try:
            return super().default(o)
        except TypeError:
            return str(o)


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


import asyncio
from fastmcp.client import Client

async def _get_tools_for_agent(agent):
    """
    Builds a list of tool definitions for the LLM, including custom and dynamically fetched MCP tools.
    """
    tool_definitions = []
    for tool in agent.tools:
        if tool.tool_type == "custom":
            tool_definitions.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters or {},
                },
            })
        elif tool.tool_type == "mcp" and tool.mcp_server_url:
            try:
                async with Client(str(tool.mcp_server_url)) as client:
                    mcp_tools = await client.list_tools()
                for mcp_tool in mcp_tools:
                    # Simplify the complex MCP schema for the LLM
                    ref_name = mcp_tool.inputSchema.get('properties', {}).get('params', {}).get('$ref', '').split('/')[-1]
                    simple_params_schema = mcp_tool.inputSchema.get('$defs', {}).get(ref_name, {})
                    
                    if not simple_params_schema:
                         # Fallback to the original schema if simplification fails
                        simple_params_schema = mcp_tool.inputSchema

                    tool_description = mcp_tool.description or f"No description available for {mcp_tool.name}."
                    tool_definitions.append({
                        "type": "function",
                        "function": {
                            "name": f"{tool.name.replace(' ', '_')}__{mcp_tool.name.replace(' ', '_')}",
                            "description": tool_description,
                            "parameters": simple_params_schema,
                        },
                    })
            except Exception as e:
                print(f"Error fetching tools from MCP server {tool.mcp_server_url}: {e}")
    
    print(f"Final tool definitions for LLM: {json.dumps(tool_definitions, indent=2)}")
    return tool_definitions

async def generate_agent_response(db: Session, agent_id: int, session_id: str, company_id: int, user_message: str):
    """
    Orchestrates the agent's response, handling tool use and broadcasting messages.
    - If a tool is called, it broadcasts a 'tool_use' message, executes the tool,
      then gets a final response from the LLM, which it saves and broadcasts.
    - If no tool is called, it saves and broadcasts the text response directly.
    - This function no longer returns the response text to the caller.
    """
    agent = agent_service.get_agent(db, agent_id, company_id)
    if not agent:
        print(f"Error: Agent not found for agent_id {agent_id}")
        return

    print(f"DEBUG: Agent retrieved: {agent.name}, Tools: {agent.tools}")

    provider_module = PROVIDER_MAP.get(agent.llm_provider)
    if not provider_module:
        print(f"Error: LLM provider '{agent.llm_provider}' not found.")
        return

    generic_tools = await _get_tools_for_agent(agent)
    db_chat_history = chat_service.get_chat_messages(db, agent_id, session_id, company_id, limit=20)
    formatted_history = format_chat_history(db_chat_history)
    formatted_history.append({"role": "user", "content": user_message})

    widget_settings = widget_settings_service.get_widget_settings(db, agent_id)
    typing_indicator_enabled = widget_settings.typing_indicator_enabled if widget_settings else False

    if typing_indicator_enabled:
        await manager.broadcast_to_session(session_id, json.dumps({"type": "typing_on", "sender": "agent"}), "agent")

    try:
        agent_api_key = vault_service.decrypt(agent.credential.encrypted_credentials) if agent.credential else None
        system_prompt = (
            "You are a helpful and precise assistant. Your primary goal is to assist users by using the tools provided. "
            "Follow these rules strictly:\n"
            "1. Examine the user's request to determine the appropriate tool.\n"
            "2. Look at the tool's schema to understand its required parameters.\n"
            "3. If the user has provided all the necessary parameters, call the tool.\n"
            "4. **Crucially, if the user has NOT provided all required parameters, you MUST ask the user for the missing information. Do NOT guess, do NOT use placeholders, and do NOT call the tool without the required information.**\n"
            "For example, if the user asks to 'get user details' and the 'get_user_details' tool requires a 'user_id', you must respond by asking 'I can do that. What is the user's ID?'\n"
            f"The user's request will be provided next. Current system instructions: {agent.prompt}"
        )
        MAX_HISTORY = 10
        formatted_history = formatted_history[-MAX_HISTORY:]
        llm_response = provider_module.generate_response(
            db=db, company_id=company_id, model_name=agent.model_name,
            system_prompt=system_prompt, chat_history=formatted_history,
            tools=generic_tools, api_key=agent_api_key
        )
    except Exception as e:
        print(f"LLM Provider Error: {e}")
        if typing_indicator_enabled:
            await manager.broadcast_to_session(session_id, json.dumps({"type": "typing_off", "sender": "agent"}), "agent")
        return
    finally:
        if typing_indicator_enabled:
            await manager.broadcast_to_session(session_id, json.dumps({"type": "typing_off", "sender": "agent"}), "agent")

    final_agent_response_text = None

    if llm_response.get('type') == 'tool_call':
        tool_name = llm_response.get('tool_name')
        parameters = llm_response.get('parameters', {})
        tool_call_id = llm_response.get('tool_call_id')

        tool_call_msg = {
            "message_type": "tool_use",
            "tool_call": {"id": tool_call_id, "type": "function", "function": {"name": tool_name, "arguments": json.dumps(parameters)}}
        }
        await manager.broadcast_to_session(session_id, json.dumps(tool_call_msg), "agent")

        # --- Tool Execution ---
        if '__' in tool_name:
            connection_name_from_llm, mcp_tool_name = tool_name.split('__', 1)
            original_connection_name = connection_name_from_llm.replace('_', ' ')
            db_tool = tool_service.get_tool_by_name(db, original_connection_name, company_id)
            if not db_tool or not db_tool.mcp_server_url:
                print(f"Error: MCP connection '{original_connection_name}' not found.")
                return
            tool_result = await tool_execution_service.execute_mcp_tool(
                db_tool=db_tool, mcp_tool_name=mcp_tool_name, parameters=parameters
            )
        else:
            db_tool = tool_service.get_tool_by_name(db, tool_name, company_id)
            if not db_tool:
                print(f"Error: Tool '{tool_name}' not found.")
                return
            tool_result = tool_execution_service.execute_custom_tool(
                db=db, tool=db_tool, company_id=company_id, session_id=session_id, parameters=parameters
            )
        
        result_content = tool_result.get('result', tool_result.get('error', 'No output'))
        
        # --- Get Final Response from LLM ---
        assistant_message = {"role": "assistant", "content": None, "tool_calls": [{"id": tool_call_id, "type": "function", "function": {"name": tool_name, "arguments": json.dumps(parameters)}}]}
        tool_response_message = {"role": "tool", "tool_call_id": tool_call_id, "name": tool_name, "content": json.dumps(result_content, cls=CustomJsonEncoder)}
        
        formatted_history.append(assistant_message)
        formatted_history.append(tool_response_message)

        # This is the new, specific prompt for summarizing the tool's output.
        final_response_prompt = (
            "You have just successfully used a tool to retrieve information for the user. "
            "The user's original query and the data from the tool are in the chat history. "
            "Your task is to synthesize this information into a concise, natural, and helpful response. "
            "Do NOT mention the tool name, tool IDs, or the fact that you are processing a tool result. "
            "Simply provide a direct and clear answer to the user's question based on the data."
        )

        final_response = provider_module.generate_response(
            db=db, company_id=company_id, model_name=agent.model_name,
            system_prompt=final_response_prompt, chat_history=formatted_history,
            tools=[], api_key=agent_api_key
        )
        final_agent_response_text = final_response.get('content', 'No response content.')

    elif llm_response.get('type') == 'text':
        final_agent_response_text = llm_response.get('content', 'No response content.')

    # --- Save and Broadcast Final Message ---
    if final_agent_response_text and final_agent_response_text.strip():
        agent_message = ChatMessageCreate(message=final_agent_response_text, message_type="message")
        db_agent_message = chat_service.create_chat_message(db, agent_message, agent_id, session_id, company_id, "agent")
        await manager.broadcast_to_session(session_id, ChatMessageSchema.model_validate(db_agent_message).model_dump_json(), "agent")
        print(f"[AgentResponse] Broadcasted final agent response to session: {session_id}")
    else:
        print(f"[AgentResponse] Final agent response was empty. Nothing to broadcast.")
        
    return final_agent_response_text