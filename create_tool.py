
from sqlalchemy.orm import Session
from app.models.tool import Tool
from app.schemas.tool import ToolCreate
from app.services import tool_service

def create_calculate_sum_tool(db: Session, company_id: int):
    tool_code = '''
def run(params, config):
    """
    Calculates the sum of two numbers, converting inputs to numbers if possible.
    Stores the result directly into the 'result' key of the exec_globals.
    """

    try:
        num1 = float(params.get('num1'))
        num2 = float(params.get('num2'))
        
        return num1 + num2
    except (ValueError, TypeError):
        return "Error: Could not convert 'num1' and 'num2' to numbers."

'''
    tool_create = ToolCreate(
        name="calculate_sum",
        description="Calculates the sum of two numbers.",
        parameters={
            "type": "object",
            "properties": {
                "num1": {"type": "number", "description": "The first number."},
                "num2": {"type": "number", "description": "The second number."}
            },
            "required": ["num1", "num2"]
        },
        code=tool_code,
        company_id=company_id
    )
    return tool_service.create_tool(db=db, tool=tool_create, company_id=company_id)
