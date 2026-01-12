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
    print(f"[LOOKUP] get_lookup_value called for: '{lookup_source}'")

    if not lookup_source:
        print(f"[LOOKUP] No lookup_source provided")
        return None

    parts = lookup_source.split(".", 1)
    if len(parts) != 2:
        print(f"[LOOKUP] Invalid format (expected 'type.field')")
        return None

    source_type, field_name = parts
    print(f"[LOOKUP] Source type: '{source_type}', Field: '{field_name}'")

    try:
        if source_type == "contact":
            # Get contact from session
            session = conversation_session_service.get_session_by_conversation_id(db, session_id, company_id)
            print(f"[LOOKUP] Session found: {session is not None}, contact_id: {session.contact_id if session else None}")
            if session and session.contact_id:
                contact = contact_service.get_contact(db, session.contact_id, company_id)
                print(f"[LOOKUP] Contact found: {contact is not None}")
                if contact:
                    value = getattr(contact, field_name, None)
                    print(f"[LOOKUP] Contact.{field_name} = '{value}'")
                    # Check if value exists and is not empty
                    if value and str(value).strip():
                        print(f"[LOOKUP] ✓ Returning value: '{value}'")
                        return value
                    else:
                        print(f"[LOOKUP] ✗ Value is empty or None")
            else:
                print(f"[LOOKUP] ✗ No contact linked to session")

        elif source_type == "context":
            # Check conversation context if provided
            print(f"[LOOKUP] Checking context for '{field_name}'")
            if context and field_name in context:
                value = context.get(field_name)
                if value and str(value).strip():
                    print(f"[LOOKUP] ✓ Found in context: '{value}'")
                    return value
            print(f"[LOOKUP] ✗ Not found in context")

        elif source_type == "session":
            # Get session metadata
            session = conversation_session_service.get_session_by_conversation_id(db, session_id, company_id)
            if session:
                value = getattr(session, field_name, None)
                if value:
                    print(f"[LOOKUP] ✓ Found in session: '{value}'")
                    return value
            print(f"[LOOKUP] ✗ Not found in session")

    except Exception as e:
        print(f"[LOOKUP] ERROR looking up {lookup_source}: {e}")

    print(f"[LOOKUP] Returning None")
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
    print(f"\n[FOLLOW-UP SERVICE] === Building follow-up response ===")
    print(f"[FOLLOW-UP SERVICE] Tool: {tool.name}")
    print(f"[FOLLOW-UP SERVICE] Provided params: {provided_params}")
    print(f"[FOLLOW-UP SERVICE] Session ID: {session_id}")

    # Check if tool has follow_up_config
    follow_up_config = tool.follow_up_config
    if not follow_up_config or not follow_up_config.get("enabled"):
        print(f"[FOLLOW-UP SERVICE] Follow-up not enabled, returning None")
        return None

    fields_config = follow_up_config.get("fields", {})
    if not fields_config:
        print(f"[FOLLOW-UP SERVICE] No fields configured, returning None")
        return None

    print(f"[FOLLOW-UP SERVICE] Fields to check: {list(fields_config.keys())}")

    # Collect all field values (from params and lookups)
    collected_values = {}

    # Check each configured field
    for field_name, field_config in fields_config.items():
        print(f"[FOLLOW-UP SERVICE] Checking field: '{field_name}'")

        # First check if already provided in params
        if field_name in provided_params and provided_params[field_name]:
            print(f"[FOLLOW-UP SERVICE]   ✓ Found in provided_params: '{provided_params[field_name]}'")
            collected_values[field_name] = provided_params[field_name]
            continue

        print(f"[FOLLOW-UP SERVICE]   ✗ Not in provided_params (value: {provided_params.get(field_name)})")

        # Try lookup source
        lookup_source = field_config.get("lookup_source")
        if lookup_source:
            print(f"[FOLLOW-UP SERVICE]   Trying lookup_source: '{lookup_source}'")
            lookup_value = get_lookup_value(db, lookup_source, session_id, company_id, context)
            if lookup_value:
                collected_values[field_name] = lookup_value
                print(f"[FOLLOW-UP SERVICE]   ✓ Auto-filled from {lookup_source}: '{lookup_value}'")
                continue
            else:
                print(f"[FOLLOW-UP SERVICE]   ✗ Lookup returned None")

        # Field is missing - return its question
        question = field_config.get("question")
        if question:
            print(f"[FOLLOW-UP SERVICE] ⚠️  MISSING FIELD '{field_name}' - returning question: '{question}'")
            return question

    # All fields collected - return completion message
    print(f"[FOLLOW-UP SERVICE] ✓ All fields collected: {collected_values}")
    completion_template = follow_up_config.get("completion_message_template")
    if completion_template:
        result = render_template(completion_template, collected_values)
        print(f"[FOLLOW-UP SERVICE] Returning completion template: '{result}'")
        return result

    completion_message = follow_up_config.get("completion_message")
    if completion_message:
        print(f"[FOLLOW-UP SERVICE] Returning completion message: '{completion_message}'")
        return completion_message

    # No completion message configured
    print(f"[FOLLOW-UP SERVICE] No completion message configured, returning None")
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
