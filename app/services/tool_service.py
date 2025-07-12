from sqlalchemy.orm import Session
from app.models import tool as models_tool
from app.schemas import tool as schemas_tool

def get_tool(db: Session, tool_id: int, company_id: int):
    return db.query(models_tool.Tool).filter(
        models_tool.Tool.id == tool_id,
        models_tool.Tool.company_id == company_id
    ).first()

def get_tool_by_name(db: Session, name: str, company_id: int):
    return db.query(models_tool.Tool).filter(
        models_tool.Tool.name == name,
        models_tool.Tool.company_id == company_id
    ).first()

def get_tools(db: Session, company_id: int, skip: int = 0, limit: int = 100):
    return db.query(models_tool.Tool).filter(
        models_tool.Tool.company_id == company_id
    ).offset(skip).limit(limit).all()

def create_tool(db: Session, tool: schemas_tool.ToolCreate, company_id: int):
    db_tool = models_tool.Tool(**tool.dict(), company_id=company_id)
    db.add(db_tool)
    db.commit()
    db.refresh(db_tool)
    return db_tool

def update_tool(db: Session, tool_id: int, tool: schemas_tool.ToolUpdate, company_id: int):
    db_tool = get_tool(db, tool_id, company_id)
    if db_tool:
        for key, value in tool.dict(exclude_unset=True).items():
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
