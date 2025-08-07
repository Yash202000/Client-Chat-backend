from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, HttpUrl
from typing import Dict, Any
from fastmcp.client import Client
import asyncio

router = APIRouter()

class McpInspectRequest(BaseModel):
    url: HttpUrl

class McpExecuteRequest(BaseModel):
    url: HttpUrl
    tool_name: str
    parameters: Dict[str, Any]

@router.post("/inspect")
async def inspect_mcp_server(request: McpInspectRequest):
    """
    Connects to an MCP server and returns a list of its available tools.
    """
    try:
        async with Client(str(request.url)) as client:
            tool_list = await client.list_tools()
            
        for tool in tool_list:
            print(tool)
        
        tools = [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.inputSchema.get('$defs', {}).get(tool.inputSchema.get('properties', {}).get('params', {}).get('$ref', '').split('/')[-1], {}),
            }
            for tool in tool_list
        ]
        
        return {"tools": tools}
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to connect or inspect MCP server. Error: {str(e)}",
        )

@router.post("/execute")
async def execute_mcp_tool(request: McpExecuteRequest):
    """
    Connects to an MCP server and executes a tool with the given parameters.
    """
    try:
        async with Client(str(request.url)) as client:
            result = await client.call_tool(request.tool_name, request.parameters)
            return {"result": result}
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to execute tool on MCP server. Error: {str(e)}",
        )
