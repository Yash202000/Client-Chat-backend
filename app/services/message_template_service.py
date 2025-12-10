"""
Service for message template variable replacement.

Replaces {{variable}} tokens with actual values from contact, agent, and company data.
Similar to campaign personalization but for chat templates.
"""

from typing import Optional
from datetime import datetime


def replace_template_variables(
    content: str,
    contact=None,  # Contact model instance
    agent=None,    # User model instance
    company=None   # Company model instance
) -> str:
    """
    Replace template variables with actual values.

    Supported variables:
    - Contact: {{contact_name}}, {{contact_first_name}}, {{contact_email}}, {{contact_phone}}, {{contact_company}}
    - Agent: {{agent_name}}, {{agent_first_name}}, {{agent_email}}
    - System: {{current_date}}, {{current_time}}, {{company_name}}

    Args:
        content: Template content with {{variable}} placeholders
        contact: Contact model instance
        agent: User (agent) model instance
        company: Company model instance

    Returns:
        Content with variables replaced
    """
    if not content:
        return content

    # Unescape markdown-escaped underscores in variable names
    # Lexical editor escapes underscores in markdown: {{contact\_name}} -> {{contact_name}}
    content = content.replace('\\\\', '\\').replace('\\_', '_')

    replacements = {}

    # Contact variables
    if contact:
        # Parse contact name
        contact_name = contact.name or ''
        name_parts = contact_name.split(' ', 1) if contact_name else []
        contact_first_name = name_parts[0] if name_parts else ''

        # Get company from custom attributes if available
        contact_company = ''
        if hasattr(contact, 'custom_attributes') and contact.custom_attributes:
            if isinstance(contact.custom_attributes, dict):
                contact_company = contact.custom_attributes.get('company', '')

        replacements.update({
            '{{contact_name}}': contact_name,
            '{{contact_first_name}}': contact_first_name,
            '{{contact_email}}': contact.email or '',
            '{{contact_phone}}': contact.phone_number or '',
            '{{contact_company}}': contact_company,
        })

    # Agent variables
    if agent:
        # Build agent full name
        agent_full_name = f"{agent.first_name or ''} {agent.last_name or ''}".strip()
        if not agent_full_name:
            # Fallback to email username
            agent_full_name = agent.email.split('@')[0] if agent.email else ''

        # Get agent first name
        agent_first_name = agent.first_name or ''
        if not agent_first_name and agent.email:
            agent_first_name = agent.email.split('@')[0]

        replacements.update({
            '{{agent_name}}': agent_full_name,
            '{{agent_first_name}}': agent_first_name,
            '{{agent_email}}': agent.email or '',
        })

    # Company variables
    if company:
        replacements.update({
            '{{company_name}}': company.name or '',
        })

    # System variables
    now = datetime.now()
    replacements.update({
        '{{current_date}}': now.strftime('%Y-%m-%d'),
        '{{current_time}}': now.strftime('%H:%M'),
    })

    # Apply all replacements
    personalized = content
    for token, value in replacements.items():
        personalized = personalized.replace(token, str(value))

    return personalized


def get_available_variables():
    """
    Get list of all available template variables.

    Returns:
        Dictionary with contact_variables, agent_variables, and system_variables
    """
    return {
        "contact_variables": [
            {"variable": "{{contact_name}}", "description": "Contact's full name"},
            {"variable": "{{contact_first_name}}", "description": "Contact's first name"},
            {"variable": "{{contact_email}}", "description": "Contact's email address"},
            {"variable": "{{contact_phone}}", "description": "Contact's phone number"},
            {"variable": "{{contact_company}}", "description": "Contact's company name"},
        ],
        "agent_variables": [
            {"variable": "{{agent_name}}", "description": "Your full name"},
            {"variable": "{{agent_first_name}}", "description": "Your first name"},
            {"variable": "{{agent_email}}", "description": "Your email address"},
        ],
        "system_variables": [
            {"variable": "{{current_date}}", "description": "Current date (YYYY-MM-DD)"},
            {"variable": "{{current_time}}", "description": "Current time (HH:MM)"},
            {"variable": "{{company_name}}", "description": "Your company name"},
        ]
    }
