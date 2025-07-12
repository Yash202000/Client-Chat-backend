from fastapi import APIRouter

from app.api.v1.endpoints import agents, webhooks, knowledge_bases, websocket_conversations, tools, workflow
from app.api.v1.endpoints import conversations
from app.api.v1.endpoints import credentials, users, user_settings, company_settings, companies, notification_settings, teams, team_memberships

api_router = APIRouter()
websocket_router = APIRouter() # New router for WebSocket endpoints

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