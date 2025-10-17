from pydantic import BaseModel, Field, HttpUrl
from typing import Optional, Dict, Any, Literal

class ToolBase(BaseModel):
    name: str = Field(..., description="The user-defined name for the tool or MCP connection.")
    description: Optional[str] = Field(None, description="A brief description of what the tool does.")
    tool_type: Literal["custom", "mcp"] = Field(..., description="The type of the tool.")

class ToolCreate(ToolBase):
    # For custom tools
    parameters: Optional[Dict[str, Any]] = Field(None, description="JSON schema for the tool's input parameters.")
    code: Optional[str] = Field(None, description="The Python code for the tool's function.")
    
    # For MCP connections
    mcp_server_url: Optional[HttpUrl] = Field(None, description="The URL of the MCP server.")

    # For pre-built tools
    pre_built_connector_name: Optional[str] = None

class ToolUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    parameters: Optional[Dict[str, Any]] = None
    code: Optional[str] = None
    mcp_server_url: Optional[HttpUrl] = None
    configuration: Optional[Dict[str, Any]] = None

class Tool(ToolBase):
    id: int
    company_id: int
    
    # Optional fields depending on tool_type
    parameters: Optional[Dict[str, Any]]
    code: Optional[str]
    mcp_server_url: Optional[HttpUrl]
    configuration: Optional[Dict[str, Any]]

    class Config:
        orm_mode = True
