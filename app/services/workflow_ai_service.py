"""
Workflow AI Chat Service

Allows users to modify workflows via natural language.
Maintains a chat history for context-aware edits.
Uses any available Groq or OpenAI credential from the company vault.
"""

import json
import logging
import math
from typing import Any, Dict, List, Optional, Tuple

from groq import AsyncGroq
from openai import AsyncOpenAI
from sqlalchemy.orm import Session

from app.services import credential_service
from app.services.vault_service import vault_service

logger = logging.getLogger(__name__)

# ── System prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are an expert AI assistant for a visual workflow builder.
You help users create and modify chat-bot workflows by understanding natural language and generating precise workflow JSON.

━━━ WORKFLOW JSON STRUCTURE ━━━
A workflow has two keys:
  "nodes": [ ...node objects... ]
  "edges": [ ...edge objects... ]

NODE OBJECT:
{
  "id": "unique-string-id",
  "type": "node_type_name",
  "data": { ...type-specific fields... },
  "position": { "x": number, "y": number }
}

EDGE OBJECT:
{
  "id": "e-{source}-{target}",
  "source": "source-node-id",
  "target": "target-node-id",
  "sourceHandle": "handle-name-or-null",
  "targetHandle": null
}

━━━ ALL NODE TYPES ━━━

── ENTRY / EXIT ──
• start          data: { label }                                   output: bottom (null handle) — REQUIRED entry point
• response       data: { label, output_value }                     NO output — terminal node — REQUIRED

── CONVERSATION ──
• listen         data: { label, variable_name, timeout:300 }       outputs: bottom (null), "error"
• prompt         data: { label, message, variable_name }           output: bottom
• form           data: { label, fields:[{name,type,label,required}] } output: bottom

── AI / LOGIC ──
• llm            data: { label, prompt, model:"gpt-4o-mini", temperature:0.7, output_variable }  outputs: bottom, "error"
• condition      data: { label, conditions:[{value:"expr"},...] }  outputs: "0","1",...,"else"  (one per condition + else)
• question_classifier  data: { label, classes:["a","b"], input_variable }   outputs: "0","1",...  (one per class)
• intent_router  data: { label, routes:[{intent,label},...] }      outputs: "0","1",...,"default"
• code           data: { label, code:"python code string" }        outputs: bottom, "error"
• data_manipulation  data: { label, expression, output_variable }  outputs: bottom, "error"

── DATA / ENTITIES ──
• entity_collector  data: { label, entities:[{name,prompt},...] }  outputs: "complete", "partial"
• check_entity      data: { label, entity_name }                   outputs: "true", "false"
• extract_entities  data: { label, entities_to_extract:[{name,description}], input_variable }  outputs: bottom, "error"
• update_context    data: { label, updates:{key:value,...} }       output: bottom
• knowledge         data: { label, knowledge_base_id:null, query:"{{context.user_message}}", output_variable }  outputs: bottom, "error"

── INTEGRATION ──
• http_request   data: { label, method:"GET", url, headers:{}, body:"", output_variable }  outputs: bottom, "error"
• tool           data: { label, tool_id:null, input_mapping:{} }   outputs: bottom, "error"
• subworkflow    data: { label, subworkflow_id:null, subworkflow_name:"" }  outputs: bottom, "error"
• channel_redirect  data: { label, channel }                       outputs: bottom, "error"

── CRM ACTIONS ──
• assign_to_agent   data: { label, message }                       output: bottom
• set_status        data: { label, status }  // active|resolved|pending  output: bottom
• tag_conversation  data: { label, tag }                           output: bottom

── LOOPS ──
• foreach_loop   data: { label, array_variable, item_variable }    outputs: "loop", "exit"
• while_loop     data: { label, condition }                        outputs: "loop", "exit"

── TRIGGERS (replace start for event-driven) ──
• trigger_whatsapp, trigger_websocket, trigger_telegram, trigger_instagram,
  trigger_twilio_voice, trigger_freeswitch
  data: { label }   output: bottom

━━━ POSITIONING RULES ━━━
• Start/first node: x=250, y=5
• Each next node below previous: y += 150, x same (250)
• Branch left path: x=80,  y=parent_y+150
• Branch right path: x=420, y=parent_y+150
• After branches rejoin: x=250, y=max(branch_y)+150
• Use descriptive IDs: "llm-analyze-intent", "condition-score-check", "response-greeting"

━━━ VARIABLE SYNTAX ━━━
Use {{context.variable_name}} in prompts/messages to reference data.
Example: "Hello {{context.name}}, how can I help?"

━━━ YOUR RULES ━━━
1. Always return the COMPLETE updated workflow (all existing nodes + your additions)
2. Preserve existing nodes/edges unless the user explicitly asks to remove/replace them
3. Generate correct edges for ALL nodes including branching paths
4. Condition node with N conditions → edges with sourceHandle "0","1",...,"N-1","else"
5. If user just asks a question (no change needed) → set visual_steps to null
6. Keep IDs stable — do NOT regenerate IDs for unchanged nodes
7. If no workflow exists yet, create one from scratch with start + relevant nodes + response

━━━ RESPONSE FORMAT (always valid JSON) ━━━
{
  "reply": "Clear human-readable explanation of what was done or answered",
  "visual_steps": { "nodes": [...], "edges": [...] } or null,
  "changed_node_ids": ["id-of-added-or-modified-nodes"]
}"""


# ── Provider helpers ───────────────────────────────────────────────────────────

PROVIDER_PRIORITY = ["openai", "groq"]

def _find_credential(db: Session, company_id: int) -> Tuple[str, str]:
    """Find first available Groq or OpenAI credential for the company."""
    for provider in PROVIDER_PRIORITY:
        cred = credential_service.get_credential_by_service_name(db, provider, company_id)
        if cred:
            api_key = vault_service.decrypt(cred.encrypted_credentials)
            return api_key, provider
    raise ValueError("No LLM credential found. Please add a Groq or OpenAI API key in the Vault.")


def _get_client(api_key: str, provider: str):
    if provider == "groq":
        return AsyncGroq(api_key=api_key, timeout=60.0)
    return AsyncOpenAI(api_key=api_key, timeout=60.0)


def _default_model(provider: str) -> str:
    return "llama-3.3-70b-versatile" if provider == "groq" else "gpt-4o-mini"


# ── Main service function ──────────────────────────────────────────────────────

async def workflow_ai_chat(
    db: Session,
    company_id: int,
    message: str,
    current_visual_steps: Optional[Dict[str, Any]],
    history: List[Dict[str, str]],
) -> Dict[str, Any]:
    """
    Process a natural-language message about a workflow.

    Returns:
        {
            "reply": str,
            "visual_steps": dict | None,
            "changed_node_ids": list[str]
        }
    """
    api_key, provider = _find_credential(db, company_id)
    client = _get_client(api_key, provider)
    model = _default_model(provider)

    # Build the current-state context block
    steps_json = json.dumps(current_visual_steps or {"nodes": [], "edges": []}, indent=2)
    state_block = f"\n\nCURRENT WORKFLOW STATE:\n```json\n{steps_json}\n```\n"

    # Build message history (last 8 turns for context)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for h in history[-8:]:
        messages.append({"role": h["role"], "content": h["content"]})

    # Inject current state into the latest user message
    messages.append({
        "role": "user",
        "content": state_block + "\nUser instruction: " + message
    })

    try:
        kwargs = dict(model=model, messages=messages, temperature=0.2, max_tokens=4096)
        # Both OpenAI and Groq support json_object response format
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
            "reply": data.get("reply", "Done."),
            "visual_steps": data.get("visual_steps"),
            "changed_node_ids": data.get("changed_node_ids", []),
        }

    except json.JSONDecodeError as e:
        logger.error(f"[WorkflowAI] JSON parse error: {e}\nRaw: {raw[:500]}")
        return {
            "reply": "I couldn't parse the AI response. Please try again.",
            "visual_steps": None,
            "changed_node_ids": [],
        }
    except Exception as e:
        logger.error(f"[WorkflowAI] LLM error: {e}")
        raise
