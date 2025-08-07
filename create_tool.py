import os
from sqlalchemy.orm import Session
from app.schemas.tool import ToolCreate
from app.services import tool_service

def create_api_call_tool(db: Session, company_id: int):
    """
    Creates the default 'API Call' tool for a given company.
    """
    tool_name = "API Call"
    tool_description = "A versatile tool to make HTTP requests to any API. Configure the method, URL, headers, and body to integrate with external services."
    
    # Get the directory of the current script
    script_dir = os.path.dirname(os.path.abspath(__file__))
    code_file_path = os.path.join(script_dir, "api_call_tool_code.py")

    # Read the tool's execution code from the separate file
    with open(code_file_path, "r") as f:
        tool_code = f.read()

    # Define the schema for the tool's parameters.
    parameter_schema = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "title": "URL",
                "description": "The full URL of the API endpoint to call.",
                "default": "https://api.example.com/data"
            },
            "method": {
                "type": "string",
                "title": "HTTP Method",
                "description": "The HTTP method to use for the request.",
                "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"],
                "default": "GET"
            },
            "headers": {
                "type": "string",
                "title": "Headers (JSON Format)",
                "description": "A JSON object representing the request headers. e.g., {\"Authorization\": \"Bearer YOUR_API_KEY\"}",
                "default": "{\n  \"Content-Type\": \"application/json\"\n}"
            },
            "body": {
                "type": "string",
                "title": "Body (JSON Format)",
                "description": "A JSON object representing the request body. Only used for POST, PUT, and PATCH methods.",
                "default": "{}"
            }
        },
        "required": ["url", "method"]
    }

    tool_create = ToolCreate(
        name=tool_name,
        description=tool_description,
        parameters=parameter_schema,
        code=tool_code,
        company_id=company_id
    )
    return tool_service.create_tool(db=db, tool=tool_create, company_id=company_id)