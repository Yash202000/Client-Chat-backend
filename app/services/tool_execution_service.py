import traceback
import asyncio
import anyio
from sqlalchemy.orm import Session
from app.models.tool import Tool
from app.services import workflow_service
from fastmcp.client import Client

def execute_custom_tool(db: Session, tool: Tool, company_id: int, session_id: str, parameters: dict):
    """
    Executes a custom tool by running its stored Python code.
    """
    if not tool.code:
        return {"error": "Tool has no code to execute."}

    local_scope = {}
    execution_globals = {
        "workflow_service": workflow_service,
        "workflow_execution_service": "workflow_execution_service" # Placeholder
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
        return {"result": result}

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
