from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session
from app.core.dependencies import get_db
from app.services import tool_service, tool_execution_service
from app.schemas.tool import Tool, ToolCreate, ToolUpdate
from typing import List, Dict, Any

from app.api.v1.endpoints import agents, companies, company_settings, contacts, conversations, credentials, integrations, notification_settings, permissions, roles, teams, user_settings, users, webhooks, knowledge_bases, websocket_conversations, tools, workflow, calls, suggestions, auth, subscription, reports, optimization, webhooks as webhook_router, ws_updates, proxy, proactive, api_keys, voices, stt, public_voice, mcp, config, calendar, teams_calendar, chat, video_calls, ai_tools, intents, profile, notifications, chat_conversation_upload, leads, campaigns, tags, segments, templates, template_ai, agent_handoff, entity_notes, message_templates, invitations, workflow_templates, twilio_voice, freeswitch_voice, security_logs, token_usage, api_channel, api_integrations, billing, system, sms, email_outbound, social, linkedin_leads, call_queue, agent_skills, voice_supervisor, dialer, drive, accounts, pipelines, deals, email_tracking, booking
from app.api.v1.endpoints import contact_import
from app.api.v1.endpoints import contact_timeline
from app.api.v1.endpoints import sequences
from app.api.v1.endpoints import forms
from app.api.v1.endpoints import campaign_sequence
from app.api.v1.endpoints import audit_logs
from app.api.v1.endpoints import data_export
from app.api.v1.endpoints.cms import content_types as cms_content_types
from app.api.v1.endpoints.cms import content_items as cms_content_items
from app.api.v1.endpoints.cms import media as cms_media
from app.api.v1.endpoints.cms import search as cms_search
from app.api.v1.endpoints.cms import categories as cms_categories
from app.api.v1.endpoints.cms import tags as cms_tags
from app.api.v1.endpoints.cms import publishing as cms_publishing
from app.api.v1.endpoints.cms import public as cms_public


api_router = APIRouter()
websocket_router = APIRouter() # New router for WebSocket endpoints


@api_router.get("/pre-built-connectors")
def get_pre_built_connectors():
    return tool_service.get_pre_built_connectors()
@api_router.post("/tools/{tool_id}/execute")
def execute_tool(
    tool_id: int,
    parameters: Dict[str, Any],
    session_id: str, # Added session_id
    db: Session = Depends(get_db),
    x_company_id: int = Header(...)
):
    return tool_execution_service.execute_tool(
        db=db, 
        tool_id=tool_id, 
        company_id=x_company_id, 
        session_id=session_id, 
        parameters=parameters
    )

api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(profile.router, prefix="/profile", tags=["profile"])
api_router.include_router(agents.router, prefix="/agents", tags=["agents"])
api_router.include_router(conversations.router, prefix="/conversations", tags=["conversations"])
api_router.include_router(credentials.router, prefix="/credentials", tags=["credentials"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(user_settings.router, prefix="/settings", tags=["settings"])
api_router.include_router(company_settings.router, prefix="/company-settings", tags=["company-settings"])
api_router.include_router(companies.router, prefix="/companies", tags=["companies"])
api_router.include_router(notification_settings.router, prefix="/notification-settings", tags=["notification-settings"])
api_router.include_router(teams.router, prefix="/teams", tags=["teams"])
api_router.include_router(roles.router, prefix="/roles", tags=["roles"])
api_router.include_router(permissions.router, prefix="/permissions", tags=["permissions"])
api_router.include_router(webhooks.router, prefix="/webhooks", tags=["webhooks"])
api_router.include_router(knowledge_bases.router, prefix="/knowledge-bases", tags=["knowledge-bases"])
api_router.include_router(workflow.router, prefix="/workflows", tags=["workflows"])
api_router.include_router(tools.router, prefix="/tools", tags=["tools"])
api_router.include_router(calls.router, prefix="/calls", tags=["calls"])
api_router.include_router(suggestions.router, prefix="/suggestions", tags=["suggestions"])
api_router.include_router(subscription.router, prefix="/subscription", tags=["subscription"])
api_router.include_router(reports.router, prefix="/reports", tags=["reports"])
api_router.include_router(optimization.router, prefix="/optimization", tags=["optimization"])
api_router.include_router(integrations.router, prefix="/integrations", tags=["integrations"])
api_router.include_router(webhook_router.router, prefix="/webhooks", tags=["webhooks"])
# ws_updates.router is included in main.py with prefix="/ws" for global company-wide WebSocket
api_router.include_router(proxy.router, prefix="/proxy", tags=["proxy"])
api_router.include_router(proactive.router, prefix="/proactive", tags=["proactive"])
api_router.include_router(api_keys.router, prefix="/api-keys", tags=["api-keys"])
api_router.include_router(voices.router, prefix="/voices", tags=["voices"])
api_router.include_router(stt.router, prefix="/stt", tags=["stt"])
api_router.include_router(public_voice.router, prefix="/ws", tags=["voice"])
api_router.include_router(mcp.router, prefix="/mcp", tags=["mcp"])
api_router.include_router(config.router, prefix="/config", tags=["config"])
api_router.include_router(system.router, prefix="/system", tags=["system"])
api_router.include_router(contacts.router, prefix="/contacts", tags=["contacts"])
api_router.include_router(contact_import.router, prefix="/contacts", tags=["contacts"])
api_router.include_router(contact_timeline.router, prefix="/contacts", tags=["contacts"])
api_router.include_router(calendar.router, prefix="/calendar", tags=["calendar"])
api_router.include_router(teams_calendar.router, prefix="/teams-calendar", tags=["teams_calendar"])
api_router.include_router(chat.router, prefix="/chat", tags=["chat"])
api_router.include_router(chat_conversation_upload.router, prefix="/chat", tags=["chat"])
api_router.include_router(notifications.router, prefix="/notifications", tags=["notifications"])
api_router.include_router(billing.router, prefix="/billing", tags=["billing"])

websocket_router.include_router(websocket_conversations.router, prefix="", tags=["conversations"])
api_router.include_router(websocket_router, prefix="/ws", tags=["WebSockets"])


api_router.include_router(video_calls.router, prefix="/video-calls", tags=["video-calls"])
api_router.include_router(agent_handoff.router, prefix="/handoff", tags=["handoff"])
api_router.include_router(ai_tools.router, prefix="/ai-tools", tags=["ai-tools"])
api_router.include_router(intents.router, prefix="/intents", tags=["intents"])

# CRM routers
api_router.include_router(accounts.router, prefix="/accounts", tags=["accounts"])
api_router.include_router(pipelines.router, prefix="/pipelines", tags=["pipelines"])
api_router.include_router(deals.router, prefix="/deals", tags=["deals"])
api_router.include_router(leads.router, prefix="/leads", tags=["leads"])
api_router.include_router(campaigns.router, prefix="/campaigns", tags=["campaigns"])
api_router.include_router(tags.router, prefix="/tags", tags=["tags"])
api_router.include_router(segments.router, prefix="/segments", tags=["segments"])
api_router.include_router(templates.router, prefix="/templates", tags=["templates"], include_in_schema=True)
api_router.include_router(template_ai.router, prefix="/templates/ai", tags=["template-ai"])
api_router.include_router(message_templates.router, prefix="/message-templates", tags=["message-templates"])
api_router.include_router(entity_notes.router, prefix="/notes", tags=["notes"])
api_router.include_router(invitations.router, prefix="/invitations", tags=["invitations"])
api_router.include_router(workflow_templates.router, prefix="/workflow-templates", tags=["workflow-templates"])

# Voice integrations
api_router.include_router(twilio_voice.router, prefix="/twilio", tags=["twilio-voice"])
api_router.include_router(freeswitch_voice.router, prefix="/freeswitch", tags=["freeswitch-voice"])
api_router.include_router(call_queue.router, prefix="/voice/queue", tags=["call-queue"])
api_router.include_router(voice_supervisor.router, prefix="/voice/supervisor", tags=["voice-supervisor"])
api_router.include_router(agent_skills.router, prefix="/agent-skills", tags=["agent-skills"])
api_router.include_router(dialer.router, prefix="/dialer", tags=["dialer"])

# Security
api_router.include_router(security_logs.router, prefix="/security-logs", tags=["security"])

# Token Usage Tracking
api_router.include_router(token_usage.router, prefix="/token-usage", tags=["token-usage"])

# External API Channel (for third-party integrations)
api_router.include_router(api_channel.router, prefix="/external", tags=["external-api"])
api_router.include_router(api_integrations.router, prefix="/api-integrations", tags=["api-integrations"])

# SMS & Email outbound
api_router.include_router(sms.router, prefix="/sms", tags=["sms"])
api_router.include_router(email_outbound.router, prefix="/email", tags=["email"])
api_router.include_router(email_tracking.router, prefix="/tracking", tags=["tracking"])
api_router.include_router(booking.router, prefix="/booking-links", tags=["booking"])
api_router.include_router(sequences.router, prefix="/sequences", tags=["sequences"])
api_router.include_router(forms.router, prefix="/forms", tags=["forms"])
api_router.include_router(campaign_sequence.router, prefix="/campaigns", tags=["campaigns"])

# Marketing Hub — Social Publishing & LinkedIn Leads
api_router.include_router(social.router, prefix="/social", tags=["social"])
api_router.include_router(linkedin_leads.router, prefix="/linkedin-leads", tags=["linkedin-leads"])

# CMS (Content Management System)
api_router.include_router(cms_content_types.router, prefix="/cms/types", tags=["cms"])
api_router.include_router(cms_content_items.router, prefix="/cms/items", tags=["cms"])
api_router.include_router(cms_media.router, prefix="/cms/media", tags=["cms"])
api_router.include_router(cms_search.router, prefix="/cms/search", tags=["cms"])
api_router.include_router(cms_categories.router, prefix="/cms/categories", tags=["cms"])
api_router.include_router(cms_tags.router, prefix="/cms/tags", tags=["cms"])
api_router.include_router(cms_publishing.router, prefix="/cms/publishing", tags=["cms"])
api_router.include_router(cms_public.router, prefix="/public/cms", tags=["cms-public"])

# Drive (company file storage)
api_router.include_router(drive.router, prefix="/drive", tags=["drive"])


# Audit Logs
api_router.include_router(audit_logs.router, prefix="/audit-logs", tags=["audit-logs"])

# Data Export
api_router.include_router(data_export.router, prefix="/export", tags=["export"])