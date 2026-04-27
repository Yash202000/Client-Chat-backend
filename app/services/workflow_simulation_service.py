"""
Workflow Simulation Service

Dry-runs a workflow's visual_steps (nodes + edges) against a test message,
returning a step-by-step execution trace without side effects.

LLM nodes are executed for real so you get realistic AI responses.
All other nodes are simulated – external calls (HTTP, tools, channels) are
mocked but their inputs are evaluated so you can see exactly what would be sent.
"""

import re
import time
import json
import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Maximum nodes to visit in a single simulation (prevents infinite loops)
MAX_STEPS = 50


# ── helpers ──────────────────────────────────────────────────────────────────

def _resolve(value: Any, ctx: Dict[str, Any]) -> Any:
    """Substitute {{context.x}} placeholders with values from ctx."""
    if not isinstance(value, str) or "{{" not in value:
        return value

    def replacer(m: re.Match) -> str:
        path = m.group(1).strip().split(".")
        if path[0] == "context":
            obj: Any = ctx
            for key in path[1:]:
                obj = obj.get(key, "") if isinstance(obj, dict) else ""
            return str(obj)
        return m.group(0)

    return re.sub(r"\{\{(.*?)\}\}", replacer, value)


def _find_start_node(nodes: List[Dict]) -> Optional[Dict]:
    trigger_types = {
        "start", "trigger_whatsapp", "trigger_websocket", "trigger_telegram",
        "trigger_instagram", "trigger_twilio_voice", "trigger_freeswitch",
    }
    for n in nodes:
        if n.get("type") in trigger_types:
            return n
    return nodes[0] if nodes else None


def _next_node_id(
    current_id: str,
    handle: Optional[str],
    edges: List[Dict],
    node_map: Dict[str, Dict],
) -> Optional[str]:
    """Return the target node id for the given source + handle."""
    for e in edges:
        if e.get("source") != current_id:
            continue
        edge_handle = e.get("sourceHandle")
        if handle is None and edge_handle in (None, "bottom", ""):
            return e.get("target")
        if handle is not None and edge_handle == handle:
            return e.get("target")
    return None


def _safe_eval_condition(expr: str, ctx: Dict[str, Any]) -> bool:
    """Evaluate a simple condition expression against the context."""
    resolved = _resolve(expr, ctx)
    try:
        safe_globals: Dict = {"__builtins__": None}
        safe_locals = {
            "context": ctx,
            "ctx": ctx,
            **ctx,
        }
        result = eval(str(resolved), safe_globals, safe_locals)  # noqa: S307
        return bool(result)
    except Exception:
        return False


# ── node simulators ──────────────────────────────────────────────────────────

def _sim_start(node: Dict, ctx: Dict) -> Tuple[str, Any, Optional[str]]:
    label = node["data"].get("label", "Start")
    return "success", f"Workflow started — test message: \"{ctx.get('user_message', '')}\"", None


def _sim_trigger(node: Dict, ctx: Dict) -> Tuple[str, Any, Optional[str]]:
    channel = node["type"].replace("trigger_", "").upper()
    return "success", f"Triggered via {channel} — message: \"{ctx.get('user_message', '')}\"", None


def _sim_listen(node: Dict, ctx: Dict) -> Tuple[str, Any, Optional[str]]:
    var = node["data"].get("variable_name", "user_input")
    ctx[var] = ctx.get("user_message", "")
    return "success", f"Captured user input → {var} = \"{ctx[var]}\"", None


def _sim_prompt(node: Dict, ctx: Dict) -> Tuple[str, Any, Optional[str]]:
    msg = _resolve(node["data"].get("message", ""), ctx)
    var = node["data"].get("variable_name", "user_input")
    ctx[var] = ctx.get("user_message", "")
    return "success", f"Would send: \"{msg}\"\nCaptures reply → {var} = \"{ctx[var]}\"", None


def _sim_form(node: Dict, ctx: Dict) -> Tuple[str, Any, Optional[str]]:
    fields = node["data"].get("fields", [])
    names = [f.get("name", "?") for f in fields]
    for n_field in names:
        ctx[n_field] = f"<test_{n_field}>"
    return "success", f"Would collect form fields: {names}\n(using placeholder test values)", None


def _sim_response(node: Dict, ctx: Dict) -> Tuple[str, Any, Optional[str]]:
    text = _resolve(node["data"].get("output_value", ""), ctx)
    return "success", f"Bot replies: \"{text}\"", None


def _sim_condition(node: Dict, ctx: Dict, edges: List[Dict], node_id: str) -> Tuple[str, Any, Optional[str]]:
    conditions = node["data"].get("conditions", [])
    for idx, cond in enumerate(conditions):
        expr = cond.get("value", "")
        resolved = _resolve(expr, ctx)
        matched = _safe_eval_condition(resolved, ctx)
        if matched:
            return "success", f"Condition #{idx} matched: `{expr}` → branch {idx}", str(idx)
    return "success", f"No condition matched → taking 'else' branch", "else"


def _sim_question_classifier(node: Dict, ctx: Dict) -> Tuple[str, Any, Optional[str]]:
    classes = node["data"].get("classes", [])
    # Deterministic: always choose first class for simulation
    chosen = 0
    label = classes[chosen] if classes else "unknown"
    return "success", f"Would classify question into: [{', '.join(classes)}]\n(simulation picks class 0 → \"{label}\")", str(chosen)


def _sim_intent_router(node: Dict, ctx: Dict) -> Tuple[str, Any, Optional[str]]:
    routes = node["data"].get("routes", [])
    return "success", f"Intent router with {len(routes)} routes → taking 'default' in simulation", "default"


def _sim_update_context(node: Dict, ctx: Dict) -> Tuple[str, Any, Optional[str]]:
    updates = node["data"].get("updates", {})
    resolved = {k: _resolve(v, ctx) for k, v in updates.items()}
    ctx.update(resolved)
    return "success", f"Updated context: {json.dumps(resolved, default=str)}", None


def _sim_check_entity(node: Dict, ctx: Dict) -> Tuple[str, Any, Optional[str]]:
    name = node["data"].get("entity_name", "")
    exists = name in ctx and ctx[name]
    branch = "true" if exists else "false"
    return "success", f"Entity '{name}' present: {exists} → branch '{branch}'", branch


def _sim_entity_collector(node: Dict, ctx: Dict) -> Tuple[str, Any, Optional[str]]:
    entities = node["data"].get("entities", [])
    names = [e.get("name") for e in entities]
    for n_ent in names:
        ctx[n_ent] = f"<test_{n_ent}>"
    return "success", f"Would collect entities: {names}\n(using placeholder values in simulation)", "complete"


def _sim_extract_entities(node: Dict, ctx: Dict) -> Tuple[str, Any, Optional[str]]:
    defs = node["data"].get("entities_to_extract", [])
    names = [e.get("name") for e in defs]
    extracted = {n: f"<test_{n}>" for n in names}
    ctx.update(extracted)
    return "success", f"Would extract entities: {names}\n→ {json.dumps(extracted)}", None


def _sim_http_request(node: Dict, ctx: Dict) -> Tuple[str, Any, Optional[str]]:
    method = node["data"].get("method", "GET")
    url = _resolve(node["data"].get("url", ""), ctx)
    out_var = node["data"].get("output_variable", "http_result")
    ctx[out_var] = {"status": 200, "body": "<simulated response>"}
    return "success", f"Would call {method} {url}\n→ {out_var} = {{status: 200, body: \"<simulated>\"}}", None


def _sim_tool(node: Dict, ctx: Dict) -> Tuple[str, Any, Optional[str]]:
    tool_id = node["data"].get("tool_id", "?")
    mapping = node["data"].get("input_mapping", {})
    resolved_mapping = {k: _resolve(v, ctx) for k, v in mapping.items()}
    return "success", f"Would call tool #{tool_id} with: {json.dumps(resolved_mapping, default=str)}", None


def _sim_subworkflow(node: Dict, ctx: Dict) -> Tuple[str, Any, Optional[str]]:
    name = node["data"].get("subworkflow_name", "unnamed")
    return "success", f"Would trigger sub-workflow: \"{name}\"", None


def _sim_channel_redirect(node: Dict, ctx: Dict) -> Tuple[str, Any, Optional[str]]:
    channel = node["data"].get("channel", "?")
    return "success", f"Would redirect conversation to channel: {channel}", None


def _sim_assign_agent(node: Dict, ctx: Dict) -> Tuple[str, Any, Optional[str]]:
    msg = _resolve(node["data"].get("message", ""), ctx)
    return "success", f"Would assign to human agent — message: \"{msg}\"", None


def _sim_set_status(node: Dict, ctx: Dict) -> Tuple[str, Any, Optional[str]]:
    status = node["data"].get("status", "resolved")
    return "success", f"Would set conversation status → {status}", None


def _sim_tag_conversation(node: Dict, ctx: Dict) -> Tuple[str, Any, Optional[str]]:
    tag = node["data"].get("tag", "")
    return "success", f"Would tag conversation: \"{tag}\"", None


def _sim_knowledge(node: Dict, ctx: Dict) -> Tuple[str, Any, Optional[str]]:
    kb_id = node["data"].get("knowledge_base_id")
    query = _resolve(node["data"].get("query", "{{context.user_message}}"), ctx)
    out_var = node["data"].get("output_variable", "kb_result")
    ctx[out_var] = "<simulated KB result>"
    return "success", f"Would query KB #{kb_id}: \"{query}\"\n→ {out_var} = \"<simulated KB result>\"", None


def _sim_foreach(node: Dict, ctx: Dict) -> Tuple[str, Any, Optional[str]]:
    arr_var = node["data"].get("array_variable", "items")
    arr = ctx.get(arr_var, [])
    count = len(arr) if isinstance(arr, list) else 0
    return "success", f"Would iterate over '{arr_var}' ({count} items) → exiting loop in simulation", "exit"


def _sim_while(node: Dict, ctx: Dict) -> Tuple[str, Any, Optional[str]]:
    cond = node["data"].get("condition", "")
    return "success", f"Would loop while: `{cond}` → exiting loop in simulation", "exit"


def _sim_code(node: Dict, ctx: Dict) -> Tuple[str, Any, Optional[str]]:
    code_preview = (node["data"].get("code") or "")[:120]
    return "success", f"Would execute Python:\n```\n{code_preview}\n```", None


def _sim_data_manipulation(node: Dict, ctx: Dict) -> Tuple[str, Any, Optional[str]]:
    expr = _resolve(node["data"].get("expression", ""), ctx)
    out_var = node["data"].get("output_variable", "result")
    try:
        safe_globals: Dict = {"__builtins__": None}
        val = eval(str(expr), safe_globals, {"context": ctx, "ctx": ctx, **ctx})  # noqa: S307
        ctx[out_var] = val
        return "success", f"Expression: `{expr}` → {out_var} = {val}", None
    except Exception as exc:
        return "error", f"Expression error: {exc}", "error"


# ── async LLM simulation ──────────────────────────────────────────────────────

async def _sim_llm(node: Dict, ctx: Dict, db: Any, company_id: int) -> Tuple[str, Any, Optional[str]]:
    """Run LLM node for real using company vault credentials."""
    prompt = _resolve(node["data"].get("prompt", ""), ctx)
    model = node["data"].get("model", "gpt-4o-mini")
    temperature = float(node["data"].get("temperature", 0.7))
    out_var = node["data"].get("output_variable", "llm_output")

    try:
        from app.services.credential_service import get_credentials
        from app.services.vault_service import vault_service

        all_creds = get_credentials(db, company_id)
        creds = [c for c in all_creds if getattr(c, "service", "").lower() in ("openai", "groq", "anthropic")]
        if not creds:
            ctx[out_var] = "[No LLM credentials configured — add OpenAI/Groq key to vault]"
            return "warning", f"Prompt: \"{prompt[:200]}\"\n→ No credentials found, skipping LLM call", None

        cred = creds[0]
        api_key = vault_service.decrypt(cred.encrypted_credentials)
        provider = getattr(cred, "service", "").lower()

        content: str = ""
        if provider == "groq":
            from groq import AsyncGroq
            client = AsyncGroq(api_key=api_key)
            resp = await client.chat.completions.create(
                model=model if "llama" in model or "mixtral" in model else "llama-3.1-8b-instant",
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                max_tokens=512,
            )
            content = resp.choices[0].message.content or ""
        elif provider == "openai":
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=api_key)
            resp = await client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                max_tokens=512,
            )
            content = resp.choices[0].message.content or ""
        elif provider == "anthropic":
            import anthropic
            client = anthropic.AsyncAnthropic(api_key=api_key)
            resp = await client.messages.create(
                model=model if "claude" in model else "claude-haiku-4-5-20251001",
                max_tokens=512,
                messages=[{"role": "user", "content": prompt}],
            )
            content = resp.content[0].text if resp.content else ""
        else:
            content = "[Unsupported provider]"

        ctx[out_var] = content
        summary = content[:300] + ("…" if len(content) > 300 else "")
        return "success", f"Prompt: \"{prompt[:200]}\"\n→ {out_var} = \"{summary}\"", None

    except Exception as exc:
        logger.warning("LLM simulation error: %s", exc)
        ctx[out_var] = f"[LLM error: {exc}]"
        return "error", f"LLM call failed: {exc}", "error"


# ── main simulation runner ────────────────────────────────────────────────────

async def simulate_workflow(
    visual_steps: Dict[str, Any],
    message: str,
    extra_context: Optional[Dict[str, Any]] = None,
    db: Any = None,
    company_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    Walk through the visual workflow graph and return a trace list.

    Each trace entry:
      { node_id, node_type, label, status, output, duration_ms }
    """
    nodes: List[Dict] = visual_steps.get("nodes", [])
    edges: List[Dict] = visual_steps.get("edges", [])

    if not nodes:
        return [{"node_id": "__error__", "node_type": "error", "label": "Empty workflow",
                 "status": "error", "output": "No nodes in workflow", "duration_ms": 0}]

    node_map: Dict[str, Dict] = {n["id"]: n for n in nodes}
    trace: List[Dict] = []

    ctx: Dict[str, Any] = {"user_message": message, **(extra_context or {})}

    current_node = _find_start_node(nodes)
    if not current_node:
        return [{"node_id": "__error__", "node_type": "error", "label": "No start node",
                 "status": "error", "output": "Workflow has no start/trigger node", "duration_ms": 0}]

    visited: set = set()
    steps = 0

    while current_node and steps < MAX_STEPS:
        node_id = current_node["id"]
        node_type = current_node.get("type", "unknown")
        label = current_node.get("data", {}).get("label", node_type)

        if node_id in visited:
            trace.append({
                "node_id": node_id, "node_type": node_type, "label": label,
                "status": "skipped", "output": "Loop detected — simulation stopped",
                "duration_ms": 0,
            })
            break
        visited.add(node_id)
        steps += 1

        t0 = time.monotonic()
        handle: Optional[str] = None
        status = "success"
        output: Any = ""

        try:
            if node_type in ("start",):
                status, output, handle = _sim_start(current_node, ctx)
            elif node_type.startswith("trigger_"):
                status, output, handle = _sim_trigger(current_node, ctx)
            elif node_type == "listen":
                status, output, handle = _sim_listen(current_node, ctx)
            elif node_type == "prompt":
                status, output, handle = _sim_prompt(current_node, ctx)
            elif node_type == "form":
                status, output, handle = _sim_form(current_node, ctx)
            elif node_type == "response":
                status, output, handle = _sim_response(current_node, ctx)
                trace.append({
                    "node_id": node_id, "node_type": node_type, "label": label,
                    "status": status, "output": output,
                    "duration_ms": int((time.monotonic() - t0) * 1000),
                })
                break  # response is always terminal
            elif node_type == "condition":
                status, output, handle = _sim_condition(current_node, ctx, edges, node_id)
            elif node_type == "question_classifier":
                status, output, handle = _sim_question_classifier(current_node, ctx)
            elif node_type == "intent_router":
                status, output, handle = _sim_intent_router(current_node, ctx)
            elif node_type == "update_context":
                status, output, handle = _sim_update_context(current_node, ctx)
            elif node_type == "check_entity":
                status, output, handle = _sim_check_entity(current_node, ctx)
            elif node_type == "entity_collector":
                status, output, handle = _sim_entity_collector(current_node, ctx)
            elif node_type == "extract_entities":
                status, output, handle = _sim_extract_entities(current_node, ctx)
            elif node_type == "http_request":
                status, output, handle = _sim_http_request(current_node, ctx)
            elif node_type == "tool":
                status, output, handle = _sim_tool(current_node, ctx)
            elif node_type == "subworkflow":
                status, output, handle = _sim_subworkflow(current_node, ctx)
            elif node_type == "channel_redirect":
                status, output, handle = _sim_channel_redirect(current_node, ctx)
            elif node_type == "assign_to_agent":
                status, output, handle = _sim_assign_agent(current_node, ctx)
            elif node_type == "set_status":
                status, output, handle = _sim_set_status(current_node, ctx)
            elif node_type == "tag_conversation":
                status, output, handle = _sim_tag_conversation(current_node, ctx)
            elif node_type == "knowledge":
                status, output, handle = _sim_knowledge(current_node, ctx)
            elif node_type == "foreach_loop":
                status, output, handle = _sim_foreach(current_node, ctx)
            elif node_type == "while_loop":
                status, output, handle = _sim_while(current_node, ctx)
            elif node_type == "code":
                status, output, handle = _sim_code(current_node, ctx)
            elif node_type == "data_manipulation":
                status, output, handle = _sim_data_manipulation(current_node, ctx)
            elif node_type == "llm":
                status, output, handle = await _sim_llm(current_node, ctx, db, company_id)
            else:
                status = "skipped"
                output = f"Node type '{node_type}' not yet supported in simulation"

        except Exception as exc:
            status = "error"
            output = f"Simulation error: {exc}"

        duration_ms = int((time.monotonic() - t0) * 1000)
        trace.append({
            "node_id": node_id,
            "node_type": node_type,
            "label": label,
            "status": status,
            "output": output,
            "duration_ms": duration_ms,
        })

        if status == "error" and handle == "error":
            # Follow error edge if available, else stop
            next_id = _next_node_id(node_id, "error", edges, node_map)
            if not next_id:
                break
            current_node = node_map.get(next_id)
        else:
            next_id = _next_node_id(node_id, handle, edges, node_map)
            current_node = node_map.get(next_id) if next_id else None

    if steps >= MAX_STEPS:
        trace.append({
            "node_id": "__limit__", "node_type": "warning", "label": "Simulation limit",
            "status": "warning", "output": f"Simulation stopped after {MAX_STEPS} steps",
            "duration_ms": 0,
        })

    return trace
