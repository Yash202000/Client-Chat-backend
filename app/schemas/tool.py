from pydantic import BaseModel, Field, HttpUrl
from typing import Optional, Dict, Any, Literal


# Follow-up question configuration schemas
class FollowUpFieldConfig(BaseModel):
    """Configuration for a single field's follow-up question"""
    question: str = Field(..., description="The question to ask when this field is missing")
    lookup_source: Optional[str] = Field(None, description="Source to check for existing value (e.g., 'contact.email', 'context.user_id')")


class FollowUpConfig(BaseModel):
    """Configuration for guided data collection follow-up questions"""
    enabled: bool = Field(default=False, description="Whether follow-up questions are enabled")
    fields: Dict[str, FollowUpFieldConfig] = Field(default_factory=dict, description="Field name to follow-up config mapping")
    completion_message: Optional[str] = Field(None, description="Message when all data is collected")
    completion_message_template: Optional[str] = Field(None, description="Template with {{field}} placeholders for completion message")


class ToolBase(BaseModel):
    name: str = Field(..., description="The user-defined name for the tool or MCP connection.")
    description: Optional[str] = Field(None, description="A brief description of what the tool does.")
    tool_type: Literal["custom", "mcp", "builtin"] = Field(..., description="The type of the tool.")

class ToolCreate(ToolBase):
    # For custom tools
    parameters: Optional[Dict[str, Any]] = Field(None, description="JSON schema for the tool's input parameters.")
    code: Optional[str] = Field(None, description="The Python code for the tool's function.")

    # For MCP connections
    mcp_server_url: Optional[HttpUrl] = Field(None, description="The URL of the MCP server.")

    # For pre-built tools
    pre_built_connector_name: Optional[str] = None

    # Follow-up questions configuration
    follow_up_config: Optional[FollowUpConfig] = Field(None, description="Configuration for guided data collection")

class ToolUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    parameters: Optional[Dict[str, Any]] = None
    code: Optional[str] = None
    mcp_server_url: Optional[HttpUrl] = None
    configuration: Optional[Dict[str, Any]] = None
    follow_up_config: Optional[FollowUpConfig] = None

class Tool(ToolBase):
    id: int
    company_id: Optional[int] = None  # None for global builtin tools
    is_pre_built: bool = False

    # Optional fields depending on tool_type
    parameters: Optional[Dict[str, Any]]
    code: Optional[str]
    mcp_server_url: Optional[HttpUrl]
    configuration: Optional[Dict[str, Any]]
    follow_up_config: Optional[Dict[str, Any]] = None  # Stored as JSON

    class Config:
        orm_mode = True
