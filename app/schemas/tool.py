from pydantic import BaseModel, Field
from typing import Optional, Dict, Any

class ToolBase(BaseModel):
    name: str = Field(..., description="The name of the tool. Must be unique.")
    description: Optional[str] = Field(None, description="A brief description of what the tool does.")
    parameters: Dict[str, Any] = Field(..., description="JSON schema for the tool's input parameters.")
    # For now, we'll store the actual function code as a string. 
    # In a more advanced system, this might point to a module/function.
    code: str = Field(..., description="The Python code for the tool's function.")

class ToolCreate(ToolBase):
    pass

class ToolUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    parameters: Optional[Dict[str, Any]] = None
    code: Optional[str] = None

class Tool(ToolBase):
    id: int

    class Config:
        orm_mode = True
