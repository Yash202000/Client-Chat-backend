"""
One conversation turn for a session, independent of the channel's transport.

Same decision order as the chat websocket: resume a paused workflow, otherwise ask the Agent
(LLM + knowledge base + tools), and run a workflow if the Agent decides to start one. Instead of
pushing text to a socket, it returns what should be said next, so phone calls (and later other
channels) can speak or render it. Messages are saved and broadcast to the inbox as usual.

Used by the contact-centre voice process; the chat websocket will move onto it later.
"""
import json
import logging
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy.orm import Session

from app.models.conversation_session import ConversationSession
from app.schemas import chat_message as schemas_chat_message
from app.services import agent_execution_service, chat_service, workflow_service
from app.services.connection_manager import manager
from app.services.workflow_execution_service import WorkflowExecutionService

logger = logging.getLogger(__name__)

AGENT_FAILURE_TEXT = "I'm having some technical difficulties. Let me connect you with a member of our team."


@dataclass
class TurnResult:
    # Spoken in order. Items are plain text, or {"text", "audio_url"} for a recorded prompt.
    say: list = field(default_factory=list)
    options: list[dict] = field(default_factory=list)  # pending prompt options (for keypad digits)
    expects: Optional[str] = None                      # "prompt" | "input" | "digits" | None
    digits: Optional[dict] = None                      # keypad collection settings when expects == "digits"
    actions: list[dict] = field(default_factory=list)  # call actions from workflow nodes: transfer_to_agent, hangup
    handoff: bool = False                               # the caller is now waiting for a human
    workflow_status: Optional[str] = None


def _text(value) -> str:
    if isinstance(value, dict):
        return str(value.get("text") or value.get("message") or "")
    return "" if value is None else str(value)


def _option_label(option) -> str:
    if isinstance(option, dict):
        return str(option.get("value") or option.get("label") or option.get("key") or "")
    return str(option)


def speakable_prompt(text: str, options: list) -> str:
    """Prompt text plus its options, numbered for the keypad: 'Press 1 for Sales, 2 for Support.'"""
    labels = [_option_label(o) for o in options if _option_label(o)]
    if not labels:
        return text
    choices = ", ".join(f"{i} for {label}" for i, label in enumerate(labels, start=1))
    return f"{text} Press {choices}.".strip()


def option_key_for_digit(options: list, digit: str) -> Optional[str]:
    """Map a keypad digit to the prompt option key it stands for (1 = first option, ...)."""
    if not digit.isdigit() or not options:
        return None
    index = int(digit) - 1
    if 0 <= index < len(options):
        option = options[index]
        return str(option.get("key", option.get("value"))) if isinstance(option, dict) else str(option)
    return None


async def _save(db: Session, session: ConversationSession, text: str, sender: str, message_type: str = "voice",
                options: Optional[list] = None) -> None:
    if not text:
        return
    message = schemas_chat_message.ChatMessageCreate(message=text, message_type=message_type)
    db_message = chat_service.create_chat_message(
        db, message, session.agent_id, session.conversation_id, session.company_id, sender,
        assignee_id=None, options=options,
    )
    payload = schemas_chat_message.ChatMessage.model_validate(db_message).model_dump(mode="json")
    await manager.broadcast_to_session(session.conversation_id, json.dumps(payload), sender)


async def save_caller_message(db: Session, session: ConversationSession, text: str) -> None:
    await _save(db, session, text, "user")


def _speech_items(raw_messages: list, out: TurnResult) -> list:
    """Response-node outputs -> speakable items; call actions are collected separately."""
    items = []
    for m in raw_messages:
        if isinstance(m, dict):
            if m.get("action"):
                out.actions.append(m["action"])
            if m.get("audio_url"):
                items.append({"text": _text(m), "audio_url": m["audio_url"]})
                continue
        if _text(m):
            items.append(_text(m))
    return items


async def _apply_workflow_result(db: Session, session: ConversationSession, result: dict, out: TurnResult) -> None:
    """Turn a workflow execution result into speech. Intermediate response nodes were already saved by the engine."""
    status = result.get("status")
    out.workflow_status = status
    messages = _speech_items(result.get("response_messages") or [], out)
    last_text = _text(messages[-1]) if messages and isinstance(messages[-1], dict) else (messages[-1] if messages else "")

    if status == "completed":
        out.say.extend(messages or ([_text(result.get("response"))] if _text(result.get("response")) else []))
        if last_text:
            await _save(db, session, last_text, "agent")  # final message isn't saved by the engine
        elif _text(result.get("response")):
            await _save(db, session, _text(result.get("response")), "agent")
    elif status == "paused_for_prompt":
        out.say.extend(messages)
        prompt = result.get("prompt") or {}
        out.options = prompt.get("options") or []
        out.expects = "prompt"
        spoken = speakable_prompt(prompt.get("text", ""), out.options)
        if spoken:
            out.say.append(spoken)
        await _save(db, session, prompt.get("text", ""), "agent", message_type="prompt", options=out.options)
    elif status == "paused_for_input":
        out.say.extend(messages)
        out.expects = "digits" if result.get("expected_input_type") == "digits" else "input"
        out.digits = result.get("digits")
        question = result.get("question_text")
        audio_url = (out.digits or {}).get("audio_url")
        if question or audio_url:
            out.say.append({"text": question or "", "audio_url": audio_url} if audio_url else question)
            if question:
                await _save(db, session, question, "agent")
    elif status == "paused_for_form":
        out.say.extend(messages)
        out.say.append("I'll need a few details from you.")
    else:
        out.say.extend(messages or ([_text(result.get("response"))] if result.get("response") else []))


async def run_workflow(db: Session, session: ConversationSession, workflow_id: int, user_message: str = "",
                       option_key: Optional[str] = None) -> TurnResult:
    """Start (or resume) a specific workflow, e.g. a phone number's entry workflow at call start."""
    out = TurnResult()
    workflow = workflow_service.get_workflow(db, workflow_id, session.company_id)
    if not workflow:
        logger.warning(f"[turn] workflow {workflow_id} not found for company {session.company_id}")
        return out
    result = await WorkflowExecutionService(db).execute_workflow(
        user_message=user_message, company_id=session.company_id, workflow=workflow,
        conversation_id=session.conversation_id, option_key=option_key, agent_id=session.agent_id,
    )
    await _apply_workflow_result(db, session, result or {}, out)
    return out


async def handle_turn(db: Session, session: ConversationSession, text: str, *, option_key: Optional[str] = None,
                      voice_language: Optional[str] = None) -> TurnResult:
    """
    Caller said `text` (or pressed a key mapped to `option_key`). The caller message must already be
    saved by the transport. Returns what to say next.
    """
    out = TurnResult()
    db.refresh(session)
    if not session.is_ai_enabled or session.waiting_for_agent:
        return out  # a human has (or is about to have) the conversation

    try:
        if session.next_step_id and session.workflow_id:
            out = await run_workflow(db, session, session.workflow_id, user_message=text, option_key=option_key)
        elif session.agent_id:
            response = await agent_execution_service.generate_agent_response(
                db, session.agent_id, session.id, session.conversation_id, session.company_id, text,
                voice=True, voice_language=voice_language,
            )
            if isinstance(response, dict) and response.get("type") == "workflow_trigger":
                out = await run_workflow(db, session, response.get("workflow_id"), user_message=text, option_key=option_key)
            elif isinstance(response, dict) and response.get("type") == "handoff":
                out.say.append(AGENT_FAILURE_TEXT)
                await _save(db, session, AGENT_FAILURE_TEXT, "agent")
                from app.services import call_service
                await call_service.request_human(db, session.conversation_id, reason=response.get("reason", "AI unavailable"))
            elif response:
                reply = response.get("text", "") if isinstance(response, dict) else str(response)
                if reply:
                    out.say.append(reply)
                    await _save(db, session, reply, "agent")
        else:
            logger.warning(f"[turn] session {session.conversation_id} has no AI agent and no paused workflow")
    except Exception:
        logger.exception(f"[turn] failed for session {session.conversation_id}")
        out.say.append("Sorry, something went wrong on our side. Could you say that again?")

    db.refresh(session)
    out.handoff = bool(session.waiting_for_agent)
    return out
