from pydantic import BaseModel, Field
from typing import Optional, Dict, Any

class ToolBase(BaseModel):
    name: str = Field(..., description="The name of the tool. Must be unique.")
    description: Optional[str] = Field(None, description="A brief description of what the tool does.")
    parameters: Dict[str, Any] = Field(..., description="JSON schema for the tool's input parameters.")
    # For now, we'll store the actual function code as a string. 
    # In a more advanced system, this might point to a module/function.
    code: str = Field(..., description="The Python code for the tool's function.")
    configuration: Optional[Dict[str, Any]] = Field(None, description="Configuration for the tool, like API keys.")

class ToolCreate(ToolBase):
    pre_built_connector_name: Optional[str] = None

class ToolUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    parameters: Optional[Dict[str, Any]] = None
    code: Optional[str] = None
    configuration: Optional[Dict[str, Any]] = None

class Tool(ToolBase):
    id: int

    class Config:
        orm_mode = True
