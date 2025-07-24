from sqlalchemy.orm import Session
from app.models import tool as models_tool
from app.schemas import tool as schemas_tool
from .pre_built_connectors import load_pre_built_connectors
from . import vault_service

def get_pre_built_connectors():
    return load_pre_built_connectors()

def get_pre_built_connector_by_name(name: str):
    return get_pre_built_connectors().get(name)

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

def get_tools(db: Session, company_id: int, skip: int = 0, limit: int = 100):
    custom_tools = db.query(models_tool.Tool).filter(
        models_tool.Tool.company_id == company_id
    ).offset(skip).limit(limit).all()
    
    for tool in custom_tools:
        if tool.configuration:
            tool.configuration = vault_service.decrypt_dict(tool.configuration)

    # Pre-built tools are now dynamically loaded and not stored in the DB
    # They are presented as templates that can be added to a company's toolset
    return custom_tools

def create_tool(db: Session, tool: schemas_tool.ToolCreate, company_id: int):
    if tool.pre_built_connector_name:
        pre_built_connector = get_pre_built_connector_by_name(tool.pre_built_connector_name)
        if not pre_built_connector:
            return None
        
        tool_data = {
            "name": pre_built_connector["name"],
            "description": pre_built_connector["description"],
            "parameters": pre_built_connector["parameters"],
            "is_pre_built": True,
        }
        db_tool = models_tool.Tool(**tool_data, company_id=company_id)
    else:
        tool_data = tool.dict(exclude={"pre_built_connector_name"})
        tool_data["is_pre_built"] = False
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
        update_data = tool.dict(exclude_unset=True)
        if "configuration" in update_data and update_data["configuration"]:
            update_data["configuration"] = vault_service.encrypt_dict(update_data["configuration"])
        
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
