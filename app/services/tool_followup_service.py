"""
Tool Follow-up Service

Handles building follow-up questions for guided data collection in tools.
When a tool is executed with missing required fields, this service checks
the tool's follow_up_config and returns the appropriate question or completion message.
"""

import re
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from app.models.tool import Tool
from app.services import conversation_session_service, contact_service


def get_lookup_value(
    db: Session,
    lookup_source: str,
    session_id: str,
    company_id: int,
    context: Optional[Dict[str, Any]] = None
) -> Optional[Any]:
    """
    Get a value from the specified lookup source.

    Supported sources:
    - contact.{field} - From linked contact (name, email, phone_number)
    - context.{key} - From conversation context
    - session.{key} - From session metadata

    Returns None if the value doesn't exist or lookup fails.
    """
    if not lookup_source:
        return None

    parts = lookup_source.split(".", 1)
    if len(parts) != 2:
        return None

    source_type, field_name = parts

    try:
        if source_type == "contact":
            # Get contact from session
            session = conversation_session_service.get_session_by_conversation_id(db, session_id, company_id)
            if session and session.contact_id:
                contact = contact_service.get_contact(db, session.contact_id, company_id)
                if contact:
                    value = getattr(contact, field_name, None)
                    # Check if value exists and is not empty
                    if value and str(value).strip():
                        return value

        elif source_type == "context":
            # Check conversation context if provided
            if context and field_name in context:
                value = context.get(field_name)
                if value and str(value).strip():
                    return value

        elif source_type == "session":
            # Get session metadata
            session = conversation_session_service.get_session_by_conversation_id(db, session_id, company_id)
            if session:
                value = getattr(session, field_name, None)
                if value:
                    return value

    except Exception as e:
        print(f"[FOLLOW-UP SERVICE] Error looking up {lookup_source}: {e}")

    return None


def render_template(template: str, data: Dict[str, Any]) -> str:
    """
    Render a template string with {{field}} placeholders.

    Example: "Thank you, {{name}}!" with {"name": "John"} -> "Thank you, John!"
    """
    def replace_placeholder(match):
        key = match.group(1)
        return str(data.get(key, f"{{{{key}}}}"))

    return re.sub(r"\{\{(\w+)\}\}", replace_placeholder, template)


def build_follow_up_response(
    db: Session,
    tool: Tool,
    provided_params: Dict[str, Any],
    session_id: str,
    company_id: int,
    context: Optional[Dict[str, Any]] = None
) -> Optional[str]:
    """
    Build a follow-up response based on tool's follow_up_config.

    This function checks:
    1. If follow-up is enabled for the tool
    2. Which required fields are missing from provided_params
    3. For each missing field, checks the lookup_source for existing value
    4. Returns the first missing field's question, or completion message if all collected

    Args:
        db: Database session
        tool: The Tool object with follow_up_config
        provided_params: Parameters provided by the user/LLM
        session_id: Current conversation session ID
        company_id: Company ID
        context: Optional conversation context dict

    Returns:
        Follow-up question, completion message, or None if not configured
    """
    # Check if tool has follow_up_config
    follow_up_config = tool.follow_up_config
    if not follow_up_config or not follow_up_config.get("enabled"):
        return None

    fields_config = follow_up_config.get("fields", {})
    if not fields_config:
        return None

    # Collect all field values (from params and lookups)
    collected_values = {}

    # Check each configured field
    for field_name, field_config in fields_config.items():
        # First check if already provided in params
        if field_name in provided_params and provided_params[field_name]:
            collected_values[field_name] = provided_params[field_name]
            continue

        # Try lookup source
        lookup_source = field_config.get("lookup_source")
        if lookup_source:
            lookup_value = get_lookup_value(db, lookup_source, session_id, company_id, context)
            if lookup_value:
                collected_values[field_name] = lookup_value
                print(f"[FOLLOW-UP SERVICE] Auto-filled {field_name} from {lookup_source}")
                continue

        # Field is missing - return its question
        question = field_config.get("question")
        if question:
            print(f"[FOLLOW-UP SERVICE] Missing field '{field_name}', asking: {question}")
            return question

    # All fields collected - return completion message
    completion_template = follow_up_config.get("completion_message_template")
    if completion_template:
        return render_template(completion_template, collected_values)

    completion_message = follow_up_config.get("completion_message")
    if completion_message:
        return completion_message

    # No completion message configured
    return None


def get_auto_filled_params(
    db: Session,
    tool: Tool,
    provided_params: Dict[str, Any],
    session_id: str,
    company_id: int,
    context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Get auto-filled parameters by checking lookup sources.

    This is useful when you want to execute a tool with automatically
    filled values from contact/context without asking the user.

    Returns a dict with the original params plus any auto-filled values.
    """
    result = dict(provided_params)

    follow_up_config = tool.follow_up_config
    if not follow_up_config or not follow_up_config.get("enabled"):
        return result

    fields_config = follow_up_config.get("fields", {})

    for field_name, field_config in fields_config.items():
        # Skip if already provided
        if field_name in result and result[field_name]:
            continue

        # Try lookup source
        lookup_source = field_config.get("lookup_source")
        if lookup_source:
            lookup_value = get_lookup_value(db, lookup_source, session_id, company_id, context)
            if lookup_value:
                result[field_name] = lookup_value
                print(f"[FOLLOW-UP SERVICE] Auto-filled param {field_name} = {lookup_value}")

    return result
