from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session
from app.core.dependencies import get_db
from app.services import tool_service, tool_execution_service
from app.schemas.tool import Tool, ToolCreate, ToolUpdate
from typing import List, Dict, Any

from app.api.v1.endpoints import agents, webhooks, knowledge_bases, websocket_conversations, tools, workflow
from app.api.v1.endpoints import conversations
from app.api.v1.endpoints import credentials, users, user_settings, company_settings, companies, notification_settings, teams, team_memberships

api_router = APIRouter()
websocket_router = APIRouter() # New router for WebSocket endpoints

@api_router.get("/pre-built-connectors")
def get_pre_built_connectors():
    return tool_service.get_pre_built_connectors()

@api_router.post("/tools/{tool_id}/execute")
def execute_tool(
    tool_id: int,
    parameters: Dict[str, Any],
    db: Session = Depends(get_db),
    x_company_id: int = Header(...)
):
    return tool_execution_service.execute_tool(
        db=db, tool_id=tool_id, company_id=x_company_id, parameters=parameters
    )

api_router.include_router(agents.router, prefix="/agents", tags=["agents"])
api_router.include_router(conversations.router, prefix="/conversations", tags=["conversations"])
websocket_router.include_router(websocket_conversations.router, prefix="/conversations", tags=["conversations"])
api_router.include_router(credentials.router, prefix="/credentials", tags=["credentials"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(user_settings.router, prefix="/settings", tags=["settings"])
api_router.include_router(company_settings.router, prefix="/company-settings", tags=["company-settings"])
api_router.include_router(companies.router, prefix="/companies", tags=["companies"])
api_router.include_router(notification_settings.router, prefix="/notification-settings", tags=["notification-settings"])
api_router.include_router(teams.router, prefix="/teams", tags=["teams"])
api_router.include_router(team_memberships.router, prefix="/team-memberships", tags=["team-memberships"])
api_router.include_router(webhooks.router, prefix="/webhooks", tags=["webhooks"])
api_router.include_router(knowledge_bases.router, prefix="/knowledge-bases", tags=["knowledge-bases"])
api_router.include_router(workflow.router, prefix="/workflows", tags=["workflows"])
api_router.include_router(tools.router, prefix="/tools", tags=["tools"])