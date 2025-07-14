import traceback
from sqlalchemy.orm import Session
from app.services import tool_service, workflow_service, workflow_execution_service, contact_service
from app.schemas import contact as schemas_contact

def _execute_update_contact_details(db: Session, company_id: int, session_id: str, parameters: dict):
    """Directly executes the logic for updating contact details."""
    contact = contact_service.get_or_create_contact_by_session(db, session_id=session_id, company_id=company_id)
    if not contact:
        return {"error": "Could not find or create a contact for this session."}
    
    contact_update = schemas_contact.ContactUpdate(**parameters)
    contact_service.update_contact(db, contact_id=contact.id, contact=contact_update, company_id=company_id)
    return {"result": f"Contact {contact.id} updated successfully with new details."}

def _execute_calculate_sum(parameters: dict):
    """Directly executes the logic for calculating a sum."""
    numbers = parameters.get("numbers", [])
    if not isinstance(numbers, list):
        return {"error": "Invalid input. 'numbers' must be a list."}
    return {"result": sum(numbers)}


def execute_tool(db: Session, tool_id: int, company_id: int, session_id: str, parameters: dict):
    """
    Executes a tool, prioritizing direct execution for built-in tools.
    """
    db_tool = tool_service.get_tool(db, tool_id, company_id)
    if not db_tool:
        return {"error": "Tool not found"}

    # --- Direct execution for built-in tools ---
    if db_tool.name == "update_contact_details":
        return _execute_update_contact_details(db, company_id, session_id, parameters)
    
    if db_tool.name == "calculate_sum":
        return _execute_calculate_sum(parameters)
    # --- End of direct execution ---


    # Fallback to dynamic execution for custom tools
    local_scope = {}
    execution_globals = {
        "workflow_service": workflow_service,
        "workflow_execution_service": workflow_execution_service
    }
    
    try:
        exec(db_tool.code, execution_globals, local_scope)
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
            "error": "An error occurred during tool execution.",
            "details": str(e),
            "traceback": traceback.format_exc()
        }
