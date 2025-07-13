import traceback
from sqlalchemy.orm import Session
from app.services import tool_service, workflow_service, workflow_execution_service

def execute_tool(db: Session, tool_id: int, company_id: int, parameters: dict):
    """
    Executes the code of a tool with the given parameters and configuration.

    Args:
        db: The database session.
        tool_id: The ID of the tool to execute.
        company_id: The ID of the company that owns the tool.
        parameters: A dictionary of parameters to pass to the tool's code.

    Returns:
        The result of the tool's execution, or an error dictionary.
    """
    db_tool = tool_service.get_tool(db, tool_id, company_id)
    if not db_tool:
        return {"error": "Tool not found"}

    # Prepare the execution environment
    local_scope = {}
    execution_globals = {
        "workflow_service": workflow_service,
        "workflow_execution_service": workflow_execution_service
    }
    
    try:
        # Execute the tool's code, which defines the 'run' function
        exec(db_tool.code, execution_globals, local_scope)
        
        # Get the 'run' function from the local scope
        tool_function = local_scope.get("run")
        
        if not callable(tool_function):
            return {"error": "Tool code does not define a callable 'run' function"}

        # Prepare the config for the tool
        config = {
            "db": db,
            "company_id": company_id
        }

        # Call the tool's 'run' function with the provided parameters and stored configuration
        result = tool_function(params=parameters, config=config)
        return {"result": result}

    except Exception as e:
        return {
            "error": "An error occurred during tool execution.",
            "details": str(e),
            "traceback": traceback.format_exc()
        }
