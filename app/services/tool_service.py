from sqlalchemy.orm import Session
from app.models import tool as models_tool
from app.schemas import tool as schemas_tool
from . import vault_service

def get_tool(db: Session, tool_id: int, company_id: int):
    db_tool = db.query(models_tool.Tool).filter(
        models_tool.Tool.id == tool_id,
        models_tool.Tool.company_id == company_id
    ).first()
    if db_tool and db_tool.configuration:
        db_tool.configuration = vault_service.decrypt_dict(db_tool.configuration)
    return db_tool

def get_tool_by_name(db: Session, name: str, company_id: int):
    db_tool = db.query(models_tool.Tool).filter(
        models_tool.Tool.name == name,
        models_tool.Tool.company_id == company_id
    ).first()
    if db_tool and db_tool.configuration:
        db_tool.configuration = vault_service.decrypt_dict(db_tool.configuration)
    return db_tool

def get_tools(db: Session, company_id: int, tool_type: str = None, skip: int = 0, limit: int = 100):
    query = db.query(models_tool.Tool).filter(
        models_tool.Tool.company_id == company_id
    )
    
    if tool_type:
        query = query.filter(models_tool.Tool.tool_type == tool_type)
        
    tools = query.offset(skip).limit(limit).all()
    
    for tool in tools:
        if tool.configuration:
            tool.configuration = vault_service.decrypt_dict(tool.configuration)

    return tools

def create_tool(db: Session, tool: schemas_tool.ToolCreate, company_id: int):
    tool_data = tool.model_dump(exclude_unset=True)
    
    if tool.tool_type == 'mcp':
        # For MCP connections, ensure code and parameters are null
        tool_data['code'] = None
        tool_data['parameters'] = None
        tool_data['mcp_server_url'] = str(tool.mcp_server_url) if tool.mcp_server_url else None
    elif tool.tool_type == 'custom':
        # For custom tools, ensure mcp_server_url is null
        tool_data['mcp_server_url'] = None
    
    if tool_data.get("configuration"):
        tool_data["configuration"] = vault_service.encrypt_dict(tool_data["configuration"])
        
    db_tool = models_tool.Tool(**tool_data, company_id=company_id)
    
    db.add(db_tool)
    db.commit()
    db.refresh(db_tool)
    return db_tool

def update_tool(db: Session, tool_id: int, tool: schemas_tool.ToolUpdate, company_id: int):
    db_tool = get_tool(db, tool_id, company_id)
    if db_tool:
        update_data = tool.model_dump(exclude_unset=True)
        if "configuration" in update_data and update_data["configuration"]:
            update_data["configuration"] = vault_service.encrypt_dict(update_data["configuration"])
        
        # Ensure consistency for tool types during update
        if db_tool.tool_type == 'mcp':
            update_data.pop('code', None)
            update_data.pop('parameters', None)
        elif db_tool.tool_type == 'custom':
            update_data.pop('mcp_server_url', None)

        for key, value in update_data.items():
            setattr(db_tool, key, value)
        
        db.commit()
        db.refresh(db_tool)
    return db_tool

def delete_tool(db: Session, tool_id: int, company_id: int):
    db_tool = get_tool(db, tool_id, company_id)
    if db_tool:
        db.delete(db_tool)
        db.commit()
    return db_tool


