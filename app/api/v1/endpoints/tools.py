from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import List

from app.schemas import tool as schemas_tool
from app.services import tool_service
from app.core.dependencies import get_current_active_user, get_db, require_permission
from app.models import user as models_user

router = APIRouter()

@router.post("/", response_model=schemas_tool.Tool, dependencies=[Depends(require_permission("tool:create"))])
def create_tool(
    tool: schemas_tool.ToolCreate,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    db_tool = tool_service.get_tool_by_name(db, name=tool.name, company_id=current_user.company_id)
    if db_tool:
        raise HTTPException(status_code=400, detail="Tool with this name already exists")
    return tool_service.create_tool(db, tool, current_user.company_id)

class McpImportRequest(BaseModel):
    mcp_connection_id: int
    tool_names: List[str]

@router.post("/import-mcp-tools", response_model=List[schemas_tool.Tool], dependencies=[Depends(require_permission("tool:create"))])
async def import_mcp_tools_endpoint(
    request: McpImportRequest,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    return await tool_service.import_mcp_tools(db, request.mcp_connection_id, request.tool_names, current_user.company_id)

@router.get("/{tool_id}", response_model=schemas_tool.Tool, dependencies=[Depends(require_permission("tool:read"))])
def get_tool(
    tool_id: int,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    db_tool = tool_service.get_tool(db, tool_id, current_user.company_id)
    if db_tool is None:
        raise HTTPException(status_code=404, detail="Tool not found")
    return db_tool

@router.get("/", response_model=List[schemas_tool.Tool], dependencies=[Depends(require_permission("tool:read"))])
def get_tools(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    return tool_service.get_tools(db, current_user.company_id, skip=skip, limit=limit)

@router.put("/{tool_id}", response_model=schemas_tool.Tool, dependencies=[Depends(require_permission("tool:update"))])
def update_tool(
    tool_id: int,
    tool: schemas_tool.ToolUpdate,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    db_tool = tool_service.update_tool(db, tool_id, tool, current_user.company_id)
    if db_tool is None:
        raise HTTPException(status_code=404, detail="Tool not found")
    return db_tool

@router.delete("/{tool_id}", dependencies=[Depends(require_permission("tool:delete"))])
def delete_tool(
    tool_id: int,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    db_tool = tool_service.delete_tool(db, tool_id, current_user.company_id)
    if db_tool is None:
        raise HTTPException(status_code=404, detail="Tool not found")
    return {"message": "Tool deleted successfully"}
