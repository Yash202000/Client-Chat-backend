"""
Workflow AI Chat Service

Allows users to modify workflows via natural language.
Uses the LLM configured on the workflow's attached agent.
Falls back to any available Groq or OpenAI credential if no agent is linked.
"""

import json
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.services import credential_service
from app.services.vault_service import vault_service
from app.llm_providers.groq_provider import generate_response as groq_generate
from app.llm_providers.openai_provider import generate_response as openai_generate
from app.llm_providers.gemini_provider import generate_response as gemini_generate

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


# ── Provider resolution ───────────────────────────────────────────────────────

_PROVIDER_MODULES = {
    "groq": groq_generate,
    "openai": openai_generate,
    "gemini": gemini_generate,
}
_FALLBACK_PROVIDER_PRIORITY = ["openai", "groq", "gemini"]
_DEFAULT_MODELS = {
    "groq": "llama-3.3-70b-versatile",
    "openai": "gpt-4o-mini",
    "gemini": "gemini-1.5-flash",
}


def _resolve_provider_and_model(db: Session, company_id: int, workflow=None):
    """
    Priority:
    1. The LLM configured on the workflow's first attached agent
    2. First available credential in the company vault (groq → gemini → openai)
    Returns (provider, model_name).
    """
    # 1. Agent-configured LLM
    if workflow is not None:
        agents = getattr(workflow, "agents", None) or []
        if agents:
            agent = agents[0]
            provider = getattr(agent, "llm_provider", None)
            model = getattr(agent, "model_name", None)
            if provider and model:
                return provider, model

    # 2. Vault fallback
    for provider in _FALLBACK_PROVIDER_PRIORITY:
        cred = credential_service.get_credential_by_service_name(db, provider, company_id)
        if cred:
            return provider, _DEFAULT_MODELS[provider]

    raise ValueError("No LLM credential found. Add an OpenAI key in the Vault, or attach an agent to this workflow.")


# ── Main service function ──────────────────────────────────────────────────────

async def workflow_ai_chat(
    db: Session,
    company_id: int,
    message: str,
    current_visual_steps: Optional[Dict[str, Any]],
    history: List[Dict[str, str]],
    workflow=None,
) -> Dict[str, Any]:
    """
    Process a natural-language message about a workflow.
    Uses the agent's configured LLM when available.
    Returns: { "reply", "visual_steps", "changed_node_ids" }
    """
    provider, model_name = _resolve_provider_and_model(db, company_id, workflow)
    generate = _PROVIDER_MODULES.get(provider, groq_generate)

    # Build history for the provider (last 8 turns)
    chat_history = []
    for h in history[-8:]:
        chat_history.append({"role": h["role"], "content": h["content"]})

    steps_json = json.dumps(current_visual_steps or {"nodes": [], "edges": []}, indent=2)
    user_content = (
        f"\n\nCURRENT WORKFLOW STATE:\n```json\n{steps_json}\n```\n"
        f"\nUser instruction: {message}"
    )

    raw = ""
    try:
        response = await generate(
            db=db,
            company_id=company_id,
            model_name=model_name,
            system_prompt=SYSTEM_PROMPT,
            chat_history=chat_history + [{"role": "user", "content": user_content}],
            tools=[],
            stream=False,
        )

        # All providers return {"content": str, ...}
        raw = (response.get("content") or "").strip()

        # Strip markdown code fences if present
        if "```" in raw:
            for part in raw.split("```"):
                candidate = part.lstrip("json").strip()
                if candidate.startswith("{"):
                    raw = candidate
                    break

        # Last-resort: extract first {...} block
        if not raw.startswith("{"):
            start, end = raw.find("{"), raw.rfind("}")
            if start != -1 and end != -1:
                raw = raw[start:end + 1]

        data = json.loads(raw.strip())
        return {
            "reply": data.get("reply", "Done."),
            "visual_steps": data.get("visual_steps"),
            "changed_node_ids": data.get("changed_node_ids", []),
        }

    except json.JSONDecodeError as e:
        logger.error(f"[WorkflowAI] JSON parse error: {e}\nRaw: {raw[:500]}")
        return {"reply": "I couldn't parse the AI response. Please try again.", "visual_steps": None, "changed_node_ids": []}
    except Exception as e:
        logger.error(f"[WorkflowAI] LLM error: {e}")
        raise
