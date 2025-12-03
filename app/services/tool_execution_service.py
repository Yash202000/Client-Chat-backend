"""
Tool execution service.
Routes tool calls to the appropriate executor based on tool type.
"""
import traceback
from typing import Optional
from sqlalchemy.orm import Session
from app.models.tool import Tool
from app.services import workflow_service, tool_followup_service, tool_service
from fastmcp.client import Client

# Import builtin tool implementations
from app.services.builtin_tools import (
    execute_handoff_tool,
    execute_create_or_update_contact_tool,
    execute_get_contact_info_tool
)

# Registry of builtin tools - maps tool name to executor function
# Add new builtin tools here
BUILTIN_TOOL_REGISTRY = {
    "request_human_handoff": execute_handoff_tool,
    "create_or_update_contact": execute_create_or_update_contact_tool,
    "get_contact_info": execute_get_contact_info_tool,
}


def execute_custom_tool(db: Session, tool: Tool, company_id: int, session_id: str, parameters: dict):
    """
    Executes a custom tool by running its stored Python code.
    Supports follow-up questions for guided data collection.
    """
    if not tool.code:
        return {"error": "Tool has no code to execute."}

    local_scope = {}
    execution_globals = {
        "workflow_service": workflow_service,
        "workflow_execution_service": "workflow_execution_service"  # Placeholder
    }

    try:
        exec(tool.code, execution_globals, local_scope)
        tool_function = local_scope.get("run")

        if not callable(tool_function):
            return {"error": "Tool code does not define a callable 'run' function"}

        config = {
            "db": db,
            "company_id": company_id,
            "session_id": session_id
        }

        result = tool_function(params=parameters, config=config)
        tool_result = {"result": result}

        # Check for follow-up questions if configured
        if tool.follow_up_config and tool.follow_up_config.get("enabled"):
            follow_up_response = tool_followup_service.build_follow_up_response(
                db=db,
                tool=tool,
                provided_params=parameters,
                session_id=session_id,
                company_id=company_id
            )
            if follow_up_response:
                tool_result["formatted_response"] = follow_up_response
                print(f"[TOOL EXECUTION] Added follow-up response: {follow_up_response}")

        return tool_result

    except Exception as e:
        return {
            "error": "An error occurred during custom tool execution.",
            "details": str(e),
            "traceback": traceback.format_exc()
        }


async def execute_mcp_tool(db_tool: Tool, mcp_tool_name: str, parameters: dict):
    """
    Executes a specific tool on a remote MCP server.
    """
    mcp_server_url = db_tool.mcp_server_url
    actual_params = parameters or {}

    print(f"DEBUG: Attempting to connect to MCP server at {mcp_server_url}")
    try:
        async with Client(mcp_server_url) as client:
            print(f"DEBUG: Connected to MCP server. Calling tool '{mcp_tool_name}' with params: {actual_params}")
            if actual_params:
                result = await client.call_tool(mcp_tool_name, arguments={"params": actual_params})
            else:
                result = await client.call_tool(mcp_tool_name)
            print(f"DEBUG: MCP tool call returned: {result}")
        return {"result": result}
    except Exception as e:
        print(f"ERROR: An unexpected error occurred during MCP tool execution: {e}")
        print(traceback.format_exc())
        return {
            "error": f"An error occurred on MCP server {mcp_server_url} while running tool '{mcp_tool_name}'.",
            "details": str(e)
        }


async def execute_tool(
    db: Session,
    tool_name: str,
    parameters: dict,
    session_id: str,
    company_id: int
) -> Optional[dict]:
    """
    Unified tool execution router.
    Routes tool calls to the appropriate executor based on tool type.

    Args:
        db: Database session
        tool_name: Name of the tool to execute
        parameters: Tool parameters
        session_id: Conversation session ID
        company_id: Company ID

    Returns:
        Tool execution result dictionary, or None if tool not found
    """
    print(f"[TOOL EXECUTION] Executing tool: {tool_name}")

    # Check if tool_name is None or empty
    if not tool_name:
        return {"error": "Tool name is required but was not provided."}

    # Check if it's a builtin tool
    if tool_name in BUILTIN_TOOL_REGISTRY:
        executor = BUILTIN_TOOL_REGISTRY[tool_name]

        # Different builtin tools have different signatures
        if tool_name == "request_human_handoff":
            return await executor(db=db, session_id=session_id, parameters=parameters)
        elif tool_name in ("create_or_update_contact", "get_contact_info"):
            if tool_name == "get_contact_info":
                return await executor(db=db, session_id=session_id, company_id=company_id)
            else:
                return await executor(db=db, session_id=session_id, company_id=company_id, parameters=parameters)

    # Check if it's an MCP tool (contains '__' separator)
    if '__' in tool_name:
        connection_name_from_llm, mcp_tool_name = tool_name.split('__', 1)
        original_connection_name = connection_name_from_llm.replace('_', ' ')
        db_tool = tool_service.get_tool_by_name(db, original_connection_name, company_id)

        if not db_tool or not db_tool.mcp_server_url:
            print(f"[TOOL EXECUTION] Error: MCP connection '{original_connection_name}' not found.")
            return {"error": f"MCP connection '{original_connection_name}' not found."}

        return await execute_mcp_tool(
            db_tool=db_tool,
            mcp_tool_name=mcp_tool_name,
            parameters=parameters
        )

    # Otherwise, it's a custom tool
    db_tool = tool_service.get_tool_by_name(db, tool_name, company_id)
    if not db_tool:
        print(f"[TOOL EXECUTION] Error: Tool '{tool_name}' not found.")
        return {"error": f"Tool '{tool_name}' not found."}

    return execute_custom_tool(
        db=db,
        tool=db_tool,
        company_id=company_id,
        session_id=session_id,
        parameters=parameters
    )
