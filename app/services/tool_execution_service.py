import traceback
import asyncio
import anyio
from sqlalchemy.orm import Session
from app.models.tool import Tool
from app.models.agent import Agent
from app.services import workflow_service, agent_assignment_service, conversation_session_service
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


async def execute_handoff_tool(db: Session, session_id: str, parameters: dict):
    """
    Executes the built-in handoff tool to transfer conversation to a human agent.

    Args:
        db: Database session
        session_id: Conversation session ID
        parameters: Tool parameters (reason, summary, priority, pool)

    Returns:
        Dictionary with handoff result
    """
    reason = parameters.get("reason", "customer_request")
    summary = parameters.get("summary", "")
    priority = parameters.get("priority", "normal")

    # Get the session to find the agent
    session = conversation_session_service.get_session(db, session_id)
    if not session or not session.agent_id:
        print(f"[HANDOFF TOOL] Session or agent not found for session_id: {session_id}")
        team_name = "Support"  # Default fallback
    else:
        # Get the agent to find the configured handoff team
        agent = db.query(Agent).filter(Agent.id == session.agent_id).first()
        if agent and agent.handoff_team_id and agent.handoff_team:
            team_name = agent.handoff_team.name
            print(f"[HANDOFF TOOL] Using agent's configured team: {team_name}")
        else:
            # Use parameter if provided, otherwise default to "Support"
            team_name = parameters.get("pool", "Support")
            print(f"[HANDOFF TOOL] Agent has no configured team, using: {team_name}")

    print(f"[HANDOFF TOOL] Session: {session_id}, Reason: {reason}, Team: {team_name}, Priority: {priority}")
    print(f"[HANDOFF TOOL] Summary: {summary}")

    try:
        # Request handoff via assignment service
        handoff_result = await agent_assignment_service.request_handoff(
            db=db,
            session_id=session_id,
            reason=reason,
            team_name=team_name,
            priority=priority
        )

        # Add summary to context
        handoff_result["summary"] = summary

        print(f"[HANDOFF TOOL] Result: {handoff_result}")
        return {"result": handoff_result}

    except Exception as e:
        print(f"[HANDOFF TOOL] Error: {e}")
        return {
            "error": "An error occurred while processing handoff request.",
            "details": str(e),
            "traceback": traceback.format_exc()
        }
