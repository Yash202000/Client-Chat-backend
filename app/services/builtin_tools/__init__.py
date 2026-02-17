"""
Builtin tools implementations.
Each builtin tool has its own module for better organization.
"""

from app.services.builtin_tools.handoff import execute_handoff_tool
from app.services.builtin_tools.contact import (
    execute_create_or_update_contact_tool,
    execute_get_contact_info_tool
)
from app.services.builtin_tools.translate import execute_translate_tool
from app.services.builtin_tools.agent_handoff import (
    execute_transfer_to_agent_tool,
    execute_consult_agent_tool
)
from app.services.builtin_tools.calendar import (
    execute_check_calendar_availability_tool,
    execute_schedule_calendar_event_tool
)
from app.services.builtin_tools.gmail import (
    execute_send_email_tool,
    execute_read_emails_tool,
    execute_get_email_content_tool
)

__all__ = [
    "execute_handoff_tool",
    "execute_create_or_update_contact_tool",
    "execute_get_contact_info_tool",
    "execute_translate_tool",
    "execute_transfer_to_agent_tool",
    "execute_consult_agent_tool",
    "execute_check_calendar_availability_tool",
    "execute_schedule_calendar_event_tool",
    "execute_send_email_tool",
    "execute_read_emails_tool",
    "execute_get_email_content_tool"
]
