from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.schemas import tool as schemas_tool
from app.services import tool_service
from app.core.dependencies import get_db, get_current_company

router = APIRouter()

@router.post("/", response_model=schemas_tool.Tool)
def create_tool(
    tool: schemas_tool.ToolCreate,
    db: Session = Depends(get_db),
    current_company_id: int = Depends(get_current_company)
):
    db_tool = tool_service.get_tool_by_name(db, name=tool.name, company_id=current_company_id)
    if db_tool:
        raise HTTPException(status_code=400, detail="Tool with this name already exists")
    return tool_service.create_tool(db, tool, current_company_id)

@router.get("/{tool_id}", response_model=schemas_tool.Tool)
def get_tool(
    tool_id: int,
    db: Session = Depends(get_db),
    current_company_id: int = Depends(get_current_company)
):
    db_tool = tool_service.get_tool(db, tool_id, current_company_id)
    if db_tool is None:
        raise HTTPException(status_code=404, detail="Tool not found")
    return db_tool

@router.get("/", response_model=List[schemas_tool.Tool])
def get_tools(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_company_id: int = Depends(get_current_company)
):
    return tool_service.get_tools(db, current_company_id, skip=skip, limit=limit)

@router.put("/{tool_id}", response_model=schemas_tool.Tool)
def update_tool(
    tool_id: int,
    tool: schemas_tool.ToolUpdate,
    db: Session = Depends(get_db),
    current_company_id: int = Depends(get_current_company)
):
    db_tool = tool_service.update_tool(db, tool_id, tool, current_company_id)
    if db_tool is None:
        raise HTTPException(status_code=404, detail="Tool not found")
    return db_tool

@router.delete("/{tool_id}")
def delete_tool(
    tool_id: int,
    db: Session = Depends(get_db),
    current_company_id: int = Depends(get_current_company)
):
    db_tool = tool_service.delete_tool(db, tool_id, current_company_id)
    if db_tool is None:
        raise HTTPException(status_code=404, detail="Tool not found")
    return {"message": "Tool deleted successfully"}
