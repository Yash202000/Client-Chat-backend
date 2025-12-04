"""
Built-in tools service for seeding and managing global built-in tools.
"""

from sqlalchemy.orm import Session
from app.models.tool import Tool

# Define built-in tools with their schemas and follow-up configurations
BUILTIN_TOOLS = [
    {
        "name": "request_human_handoff",
        "description": "Request to transfer the conversation to a human agent. Use this when the customer explicitly asks for a human, when the issue is too complex for AI, or when escalation is needed.",
        "tool_type": "builtin",
        "is_pre_built": True,
        "parameters": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "The reason for requesting handoff (e.g., customer_request, complex_issue, escalation, or technical_support)"
                },
                "summary": {
                    "type": "string",
                    "description": "A brief summary of the conversation to help the human agent understand the context"
                }
            },
            "required": ["reason", "summary"]
        },
        "follow_up_config": {
            "enabled": True,
            "fields": {
                "reason": {
                    "question": "Could you please tell me why you'd like to speak with a human agent?",
                    "lookup_source": None
                },
                "summary": {
                    "question": "Can you briefly describe what you need help with?",
                    "lookup_source": None
                }
            },
            "completion_message": "I'm connecting you with a human agent now. They'll be with you shortly."
        }
    },
    {
        "name": "create_or_update_contact",
        "description": "Saves or updates contact information for the current conversation. Call this IMMEDIATELY after collecting each piece of information (name, email, or phone). You can provide one, two, or all three fields at once. IMPORTANT: You must collect ALL THREE fields (name, email, phone) from the user - call this tool multiple times if needed to update as you collect more information.",
        "tool_type": "builtin",
        "is_pre_built": True,
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "The contact's full name"
                },
                "email": {
                    "type": "string",
                    "description": "The contact's email address"
                },
                "phone_number": {
                    "type": "string",
                    "description": "The contact's phone number"
                }
            }
        },
        "follow_up_config": {
            "enabled": True,
            "fields": {
                "name": {
                    "question": "To get started, may I have your name?",
                    "lookup_source": "contact.name"
                },
                "email": {
                    "question": "Great! And what's your email address?",
                    "lookup_source": "contact.email"
                },
                "phone_number": {
                    "question": "Perfect! Lastly, what's your phone number?",
                    "lookup_source": "contact.phone_number"
                }
            },
            "completion_message_template": "Thank you, {{name}}! How can I help you today?"
        }
    },
    {
        "name": "get_contact_info",
        "description": "Retrieves the contact information for the current conversation if available. Returns null if no contact has been created yet.",
        "tool_type": "builtin",
        "is_pre_built": True,
        "parameters": {
            "type": "object",
            "properties": {}
        },
        "follow_up_config": {
            "enabled": True,
            "fields": {
                "name": {
                    "question": "To get started, may I have your name?",
                    "lookup_source": "contact.name"
                },
                "email": {
                    "question": "Great! And what's your email address?",
                    "lookup_source": "contact.email"
                },
                "phone_number": {
                    "question": "Perfect! Lastly, what's your phone number?",
                    "lookup_source": "contact.phone_number"
                }
            },
            "completion_message_template": "Hello, {{name}}! How can I help you today?"
        }
    },
    {
        "name": "translate",
        "description": "Translates text from any language to a target language. Supports LLM-based translation (default) or Google Translate API. Use this when the user needs text translated to another language.",
        "tool_type": "builtin",
        "is_pre_built": True,
        "parameters": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "The text to translate"
                },
                "target_language": {
                    "type": "string",
                    "enum": ["en", "ar", "es", "fr", "de", "zh", "ja", "ko", "pt", "ru", "hi", "it", "nl", "tr", "pl", "vi", "th", "id"],
                    "description": "Target language code"
                },
                "source_language": {
                    "type": "string",
                    "enum": ["auto", "en", "ar", "es", "fr", "de", "zh", "ja", "ko", "pt", "ru", "hi", "it", "nl", "tr", "pl", "vi", "th", "id"],
                    "description": "Source language code. Select 'auto' for auto-detection."
                },
                "provider": {
                    "type": "string",
                    "enum": ["llm", "google"],
                    "description": "Translation provider: 'llm' uses the configured LLM (default), 'google' uses Google Translate API"
                },
                "llm_model": {
                    "type": "string",
                    "enum": [
                        "groq/llama-3.3-70b-versatile",
                        "groq/llama-3.1-8b-instant",
                        "openai/gpt-4o",
                        "openai/gpt-4o-mini",
                        "gemini/gemini-1.5-pro",
                        "gemini/gemini-1.5-flash"
                    ],
                    "description": "LLM model to use for translation (only applies when provider is 'llm')"
                }
            },
            "required": ["text", "target_language"]
        },
        "follow_up_config": None
    }
]


def seed_builtin_tools(db: Session) -> None:
    """
    Seeds built-in tools into the database.
    This is idempotent - only creates tools that don't already exist.
    Built-in tools have company_id = None (global).
    """
    for tool_data in BUILTIN_TOOLS:
        # Check if tool already exists (by name and builtin type)
        existing_tool = db.query(Tool).filter(
            Tool.name == tool_data["name"],
            Tool.tool_type == "builtin",
            Tool.company_id.is_(None)
        ).first()

        if not existing_tool:
            new_tool = Tool(
                name=tool_data["name"],
                description=tool_data["description"],
                tool_type=tool_data["tool_type"],
                is_pre_built=tool_data["is_pre_built"],
                parameters=tool_data["parameters"],
                follow_up_config=tool_data.get("follow_up_config"),
                company_id=None,  # Global tool
                code=None,
                mcp_server_url=None,
                configuration=None
            )
            db.add(new_tool)
            print(f"[BUILTIN TOOLS] Created built-in tool: {tool_data['name']}")
        else:
            # Update the description/parameters/follow_up_config if they've changed
            if existing_tool.description != tool_data["description"]:
                existing_tool.description = tool_data["description"]
            if existing_tool.parameters != tool_data["parameters"]:
                existing_tool.parameters = tool_data["parameters"]
            if existing_tool.follow_up_config != tool_data.get("follow_up_config"):
                existing_tool.follow_up_config = tool_data.get("follow_up_config")
            print(f"[BUILTIN TOOLS] Built-in tool already exists: {tool_data['name']}")

    db.commit()
    print("[BUILTIN TOOLS] Built-in tools seeding complete.")


def get_builtin_tools(db: Session) -> list:
    """
    Returns all built-in tools.
    """
    return db.query(Tool).filter(
        Tool.tool_type == "builtin",
        Tool.company_id.is_(None)
    ).all()
