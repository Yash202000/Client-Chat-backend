"""
Tool AI Chat Service

Allows users to create custom tools via natural language conversation.
Asks clarifying questions then generates a complete tool definition.
Uses any available OpenAI or Groq credential from the company vault.
"""

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from groq import AsyncGroq
from openai import AsyncOpenAI
from sqlalchemy.orm import Session

from app.services import credential_service
from app.services.vault_service import vault_service

logger = logging.getLogger(__name__)

# ── System prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are an expert AI assistant that helps users create custom tools for a chatbot platform.
Your job is to ask clarifying questions and then generate a complete, working tool definition.

━━━ TOOL STRUCTURE ━━━
A tool has these fields:
  "name": snake_case identifier (e.g. "send_slack_message")
  "description": short human-readable description of what the tool does
  "tool_type": always "custom"
  "parameters": JSON Schema object describing the tool's input parameters
  "code": Python function with signature: def run(params, config):
  "follow_up_config": optional config for asking follow-up questions

━━━ CODE RULES ━━━
• Signature must be exactly: def run(params, config):
• params: dict of inputs (keys match parameter names in the schema)
• config: dict with keys "db", "company_id", "session_id"
• Return value must be a string or JSON-serializable dict
• Use params.get("field_name") to safely access inputs
• Import standard libraries inside the function if needed (requests, json, etc.)
• Handle errors gracefully — return error message as string on failure

━━━ PARAMETERS JSON SCHEMA ━━━
Format:
{
  "type": "object",
  "properties": {
    "field_name": {
      "type": "string",  // or "number", "boolean", "array"
      "description": "what this field is"
    }
  },
  "required": ["field1", "field2"]
}

━━━ FOLLOW-UP CONFIG ━━━
Use follow_up_config when the tool needs runtime values that aren't known at call time.
Examples: asking user for their email, confirmation, or preference.
Format:
{
  "enabled": true,
  "fields": {
    "field_name": {
      "type": "ask_user",  // or "from_context"
      "question": "What is your email address?",
      "context_key": "contact.email"  // for from_context type
    }
  }
}
Set follow_up_config to null if no follow-up is needed.

━━━ EXAMPLE TOOLS ━━━

Example 1 — HTTP Request:
name: "fetch_weather"
description: "Fetches current weather for a city using OpenWeatherMap API"
parameters: { "type": "object", "properties": { "city": { "type": "string", "description": "City name" }, "api_key": { "type": "string", "description": "OpenWeatherMap API key" } }, "required": ["city", "api_key"] }
code:
def run(params, config):
    import requests
    city = params.get("city", "")
    api_key = params.get("api_key", "")
    url = f"https://api.openweathermap.org/data/2.5/weather?q={city}&appid={api_key}&units=metric"
    try:
        resp = requests.get(url, timeout=10)
        data = resp.json()
        if resp.status_code == 200:
            temp = data["main"]["temp"]
            desc = data["weather"][0]["description"]
            return f"Weather in {city}: {temp}°C, {desc}"
        return f"Error: {data.get('message', 'Unknown error')}"
    except Exception as e:
        return f"Request failed: {str(e)}"

Example 2 — Email:
name: "send_email"
description: "Sends an email via SendGrid"
parameters: { "type": "object", "properties": { "to_email": { "type": "string", "description": "Recipient email" }, "subject": { "type": "string", "description": "Email subject" }, "body": { "type": "string", "description": "Email body text" }, "api_key": { "type": "string", "description": "SendGrid API key" } }, "required": ["to_email", "subject", "body", "api_key"] }
code:
def run(params, config):
    import requests
    url = "https://api.sendgrid.com/v3/mail/send"
    headers = {"Authorization": f"Bearer {params.get('api_key')}", "Content-Type": "application/json"}
    payload = {
        "personalizations": [{"to": [{"email": params.get("to_email")}]}],
        "from": {"email": "noreply@example.com"},
        "subject": params.get("subject"),
        "content": [{"type": "text/plain", "value": params.get("body")}]
    }
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=10)
        if resp.status_code in (200, 202):
            return "Email sent successfully"
        return f"Failed to send email: {resp.status_code}"
    except Exception as e:
        return f"Error: {str(e)}"

━━━ CONVERSATION STAGES ━━━
You operate in two stages:

STAGE "questioning":
- You need more information to build the tool
- Ask ONE focused question at a time
- Key things to clarify: what the tool does, what API/service it uses, what inputs it needs,
  how to authenticate, what to return, whether to ask the user for any values at runtime
- Set "tool" to null

STAGE "preview":
- You have enough information to generate the complete tool
- Generate the full tool definition with working Python code
- Set "tool" to the complete tool object

Transition to "preview" after 3-5 exchanges OR when you have enough info to write the code.
If the user describes something very clear and specific in their first message, go straight to "preview".

━━━ RESPONSE FORMAT (always valid JSON) ━━━
{
  "stage": "questioning" | "preview",
  "reply": "human-readable message — question or confirmation",
  "tool": null | {
    "name": "snake_case_name",
    "description": "Short description of what the tool does",
    "tool_type": "custom",
    "parameters": { "type": "object", "properties": {...}, "required": [...] },
    "code": "def run(params, config):\\n    ...",
    "follow_up_config": null | { "enabled": true, "fields": {...} }
  }
}

Always return valid JSON. Never include markdown fences in your response."""


# ── Provider helpers ───────────────────────────────────────────────────────────

PROVIDER_PRIORITY = ["openai", "groq"]


def _find_credential(db: Session, company_id: int) -> Tuple[str, str]:
    """Find first available OpenAI or Groq credential for the company."""
    for provider in PROVIDER_PRIORITY:
        cred = credential_service.get_credential_by_service_name(db, provider, company_id)
        if cred:
            api_key = vault_service.decrypt(cred.encrypted_credentials)
            return api_key, provider
    raise ValueError("No LLM credential found. Please add an OpenAI or Groq API key in the Vault.")


def _get_client(api_key: str, provider: str):
    if provider == "groq":
        return AsyncGroq(api_key=api_key, timeout=60.0)
    return AsyncOpenAI(api_key=api_key, timeout=60.0)


def _default_model(provider: str) -> str:
    return "llama-3.3-70b-versatile" if provider == "groq" else "gpt-4o-mini"


# ── Main service function ──────────────────────────────────────────────────────

async def tool_ai_chat(
    db: Session,
    company_id: int,
    message: str,
    history: List[Dict[str, str]],
    existing_tool: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Process a natural-language message about creating a tool.

    Returns:
        {
            "stage": "questioning" | "preview",
            "reply": str,
            "tool": dict | None
        }
    """
    api_key, provider = _find_credential(db, company_id)
    client = _get_client(api_key, provider)
    model = _default_model(provider)

    system_content = SYSTEM_PROMPT
    if existing_tool:
        tool_json = json.dumps(existing_tool, indent=2)
        system_content += f"\n\n━━━ EXISTING TOOL (user wants to modify this) ━━━\n```json\n{tool_json}\n```\nThe user is editing this tool. Apply their requested changes and return the complete updated tool definition in the preview stage. Preserve any fields the user does not mention."

    messages = [{"role": "system", "content": system_content}]
    for h in history[-8:]:
        messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": message})

    raw = ""
    try:
        kwargs = dict(model=model, messages=messages, temperature=0.3, max_tokens=4096)
        kwargs["response_format"] = {"type": "json_object"}
        response = await client.chat.completions.create(**kwargs)
        raw = response.choices[0].message.content.strip()

        # Strip markdown code fences if present
        if "```" in raw:
            parts = raw.split("```")
            for part in parts:
                candidate = part.lstrip("json").strip()
                if candidate.startswith("{"):
                    raw = candidate
                    break

        # Last-resort: extract first {...} block
        if not raw.startswith("{"):
            start = raw.find("{")
            end = raw.rfind("}")
            if start != -1 and end != -1:
                raw = raw[start:end + 1]

        raw = raw.strip()
        data = json.loads(raw)
        return {
            "stage": data.get("stage", "questioning"),
            "reply": data.get("reply", "Tell me more about the tool you want to create."),
            "tool": data.get("tool"),
        }

    except json.JSONDecodeError as e:
        logger.error(f"[ToolAI] JSON parse error: {e}\nRaw: {raw[:500]}")
        return {
            "stage": "questioning",
            "reply": "I couldn't parse the AI response. Please try again.",
            "tool": None,
        }
    except Exception as e:
        logger.error(f"[ToolAI] LLM error: {e}")
        raise
