import os
import sys
import json

# Add the project root to the Python path to allow for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal
from app.schemas.tool import ToolCreate
from app.services import tool_service

def setup_api_tool():
    """
    Sets up the API Call tool by registering it in the database.
    """
    db = SessionLocal()
    try:
        # For this setup script, we'll assume a default company_id of 1.
        # In a real multi-tenant app, this might be handled differently.
        company_id = 1

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

        # Use the tool_service to create the tool in the database
        db_tool = tool_service.get_tool_by_name(db=db, name=tool_name, company_id=company_id)
        if db_tool:
            print(f"Tool '{tool_name}' already exists for company_id {company_id}.")
        else:
            tool_service.create_tool(db=db, tool=tool_create, company_id=company_id)
            print(f"Successfully created the '{tool_name}' tool for company_id {company_id}.")

    finally:
        db.close()

if __name__ == "__main__":
    setup_api_tool()
