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

async def execute_mcp_tool(mcp_server_url: str, tool_name: str, parameters: dict):
    """
    Executes a specific tool on a remote MCP server using the high-level .run() method.
    Includes a retry mechanism for connection errors.
    """
    max_retries = 3
    backoff_delay = 0.5  # seconds

    # The LLM can return parameters in several ways. We need to find the actual arguments.
    # Sometimes they are nested under 'params', sometimes not.
    # If no params are provided, default to an empty dict.
    actual_params = parameters.get('params', parameters)

    for attempt in range(max_retries):
        print(f"DEBUG: MCP tool execution attempt {attempt + 1} for '{tool_name}' with params: {actual_params}")
        try:
            async with Client(mcp_server_url) as client:
                # Pass parameters in a dictionary under the 'params' key
                result = await client.call_tool(tool_name, arguments={"params": actual_params})
            return {"result": result}

        except anyio.ClosedResourceError as e:
            print(f"WARNING: Attempt {attempt + 1} failed with ClosedResourceError: {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(backoff_delay * (2 ** attempt))
                print(f"INFO: Retrying MCP tool execution...")
            else:
                print(f"ERROR: MCP tool execution failed after {max_retries} attempts due to connection issues.")
                return {
                    "error": f"MCP connection failed after multiple retries on server {mcp_server_url}.",
                    "details": str(e)
                }
        except Exception as e:
            # This will catch tool execution errors raised by client.run(), like validation errors.
            print(f"ERROR: An unexpected error occurred during MCP tool execution: {e}")
            print(traceback.format_exc())
            return {
                "error": f"An error occurred on MCP server {mcp_server_url} while running tool '{tool_name}'.",
                "details": str(e)
            }
