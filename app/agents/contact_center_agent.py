"""
AgentConnect voice process for phone calls (LiveKit SIP contact centre).

Audio plumbing only: it joins each call room LiveKit SIP creates for "ai" numbers and is the ears
and mouth of the existing HeyGenAlly Agent. LiveKit handles VAD, speech-to-text, text-to-speech
and interruptions; every caller turn goes to conversation_turn_service (workflows, the Agent's
prompt, knowledge bases, tools, handoff) — the same code chat uses. No agent logic lives here.

Call flow: greet (or run the number's entry workflow) -> caller speaks / presses keys -> reply ->
on handoff, keep the caller on hold until a human agent joins from the browser, then leave.
Numbers in "direct" routing mode don't use this process (agents answer in the browser).

Run from backend/:
    python -m app.agents.contact_center_agent dev      # development (auto-reload)
    python -m app.agents.contact_center_agent start    # production
"""
import asyncio
import json
import logging
import time
from typing import Optional

from livekit import rtc
from livekit.agents import (
    Agent, AgentSession, AutoSubscribe, JobContext, JobProcess, StopResponse, WorkerOptions, cli, llm,
)

from app.core.config import settings

logger = logging.getLogger("contact-center-voice")

OPENAI_VOICES = {"alloy", "ash", "ballad", "coral", "echo", "fable", "nova", "onyx", "sage", "shimmer", "verse"}
GREETING = {
    "en": "Hello, thank you for calling. How can I help you today?",
    "ar": "مرحباً، شكراً لاتصالك. كيف يمكنني مساعدتك اليوم؟",
}
HOLD = {
    "en": "Please hold while I connect you to a member of our team.",
    "ar": "يرجى الانتظار بينما أقوم بتحويلك إلى أحد أعضاء فريقنا.",
}
STILL_HOLDING = {
    "en": "Thank you for holding. Someone will be with you shortly.",
    "ar": "شكراً لانتظارك. سيكون أحد أعضاء فريقنا معك قريباً.",
}
NO_AGENT = {
    "en": "Sorry, all of our team members are busy right now. I can keep helping you, or you can call back later.",
    "ar": "عذراً، جميع أعضاء فريقنا مشغولون حالياً. يمكنني مواصلة مساعدتك، أو يمكنك الاتصال لاحقاً.",
}


def _lang(code: Optional[str]) -> str:
    return (code or "en").split("-")[0].lower()


def _pick(texts: dict, language: str) -> str:
    return texts.get(_lang(language), texts["en"])


# ---------------------------------------------------------------- blocking DB helpers (run via to_thread)

def _db_call(fn, *args, **kwargs):
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        return fn(db, *args, **kwargs)
    finally:
        db.close()


def _open_call(db, phone_number_id: Optional[int], room_name: str, attrs: dict) -> Optional[dict]:
    """Load the number + its Agent and create (or find) the call record; the AI has answered it."""
    from app.models.agent import Agent as AgentModel
    from app.models.phone_number import PhoneNumber
    from app.services import call_service

    phone = db.query(PhoneNumber).filter(PhoneNumber.id == phone_number_id).first() if phone_number_id else None
    if not phone:
        return None
    call, created = call_service.get_or_create_inbound_call(
        db, phone=phone, room_name=room_name, sip_call_id=attrs.get("sip.callID") or room_name,
        caller=attrs.get("sip.phoneNumber"), called=attrs.get("sip.trunkPhoneNumber"),
    )
    call_service.mark_answered(db, call, None, actor_type="ai")
    agent = db.query(AgentModel).filter(AgentModel.id == phone.default_agent_id).first() if phone.default_agent_id else None
    return {
        "call": call_service.serialize(call),
        "created": created,
        "call_id": call.id,
        "company_id": phone.company_id,
        "conversation_id": call.conversation_id,
        "entry_workflow_id": phone.entry_workflow_id,
        "language": _lang(phone.language or (agent.language if agent else None)),
        "agent": {
            "id": agent.id, "name": agent.name, "welcome_message": agent.welcome_message,
            "stt_provider": agent.stt_provider, "tts_provider": agent.tts_provider, "voice_id": agent.voice_id,
        } if agent else None,
        "keys": _speech_keys(db, phone.company_id),
    }


def _speech_keys(db, company_id: int) -> dict:
    """Company credentials (vault) first, then system keys from settings."""
    from app.services import credential_service

    keys = {}
    for service in ("openai", "deepgram"):
        try:
            cred = credential_service.get_credential_by_service_name(db, service, company_id)
            if cred:
                keys[service] = credential_service.get_decrypted_credential(db, cred.id, company_id)
        except Exception:
            logger.exception(f"could not read {service} credential for company {company_id}")
    if not keys.get("openai") and settings.OPENAI_API_KEY:
        keys["openai"] = settings.OPENAI_API_KEY
    if not keys.get("deepgram") and settings.DEEPGRAM_API_KEY:
        keys["deepgram"] = settings.DEEPGRAM_API_KEY
    return {k: v for k, v in keys.items() if v}


def _record(db, call_id: int, type: str, actor_type: str = "system", payload: Optional[dict] = None):
    from app.models.voice_call import VoiceCall
    from app.services import call_service

    call = db.query(VoiceCall).filter(VoiceCall.id == call_id).one()
    call_service.record_event(db, call, type, actor_type=actor_type, payload=payload)


def _finish(db, call_id: int, ended_by: str) -> Optional[dict]:
    from app.models.voice_call import VoiceCall
    from app.services import call_service

    call = db.query(VoiceCall).filter(VoiceCall.id == call_id).one()
    return call_service.serialize(call) if call_service.finish_call(db, call, ended_by) else None


def _new_call_payloads(db, call_id: int) -> list[dict]:
    from app.models.voice_call import VoiceCall
    from app.services import call_service

    return call_service.new_call_payloads(db, db.query(VoiceCall).filter(VoiceCall.id == call_id).one())


def _give_back_to_ai(db, call_id: int) -> None:
    from app.models.voice_call import VoiceCall
    from app.services import call_service

    call_service.give_back_to_ai(db, db.query(VoiceCall).filter(VoiceCall.id == call_id).one())


async def _after_call_ended(call_id: int) -> None:
    """Queue entry + agent state bookkeeping once the call record is closed (caller hung up / IVR ended it)."""
    from app.core.database import SessionLocal
    from app.models.voice_call import VoiceCall
    from app.services import acd_service

    db = SessionLocal()
    try:
        call = db.query(VoiceCall).filter(VoiceCall.id == call_id).one()
        await acd_service.on_call_ended(db, call)
    finally:
        db.close()


async def _broadcast(company_id: Optional[int], payload: dict) -> None:
    """Live event to the company's dashboards via Redis fan-out (this process has no websockets)."""
    if not company_id:
        return
    from app.services.connection_manager import manager

    if not manager.fanout_enabled:
        logger.warning("Redis not configured (REDIS_URL / REDIS_SENTINELS): call events from the voice process cannot reach dashboards")
        return
    await manager.broadcast_to_company(company_id, json.dumps(payload, default=str))


# ---------------------------------------------------------------- recorded prompts

_AUDIO_DIR = None


async def _fetch_audio(url: str) -> Optional[str]:
    """Download (once) a recorded prompt to a local cache file; LiveKit decodes it from disk."""
    import hashlib
    import os
    import tempfile
    import httpx

    global _AUDIO_DIR
    if _AUDIO_DIR is None:
        _AUDIO_DIR = os.path.join(tempfile.gettempdir(), "agentconnect-ivr-audio")
        os.makedirs(_AUDIO_DIR, exist_ok=True)
    ext = os.path.splitext(url.split("?")[0])[1][:5] or ".audio"
    path = os.path.join(_AUDIO_DIR, hashlib.sha256(url.encode()).hexdigest() + ext)
    if os.path.exists(path):
        return path
    try:
        if url.startswith(("http://", "https://")):
            async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
                res = await client.get(url)
                res.raise_for_status()
                with open(path + ".part", "wb") as f:
                    f.write(res.content)
            os.replace(path + ".part", path)
            return path
        return url if os.path.exists(url) else None  # local file path (on-prem)
    except Exception:
        logger.exception(f"could not fetch IVR audio {url}")
        return None


# ---------------------------------------------------------------- speech providers

def _build_speech(info: dict):
    """STT/TTS from the Agent's settings and the company's keys. Returns (stt, tts); either may be None."""
    keys, agent, language = info["keys"], info["agent"] or {}, info["language"]
    stt = tts = None
    if (agent.get("stt_provider") or "deepgram") == "deepgram" and keys.get("deepgram"):
        from livekit.plugins import deepgram
        stt = deepgram.STT(model=settings.TELEPHONY_DEEPGRAM_MODEL, language=language, api_key=keys["deepgram"])
    elif keys.get("openai"):
        from livekit.plugins import openai
        stt = openai.STT(language=language, api_key=keys["openai"])
    if keys.get("openai"):
        from livekit.plugins import openai
        voice = agent.get("voice_id") if agent.get("voice_id") in OPENAI_VOICES else "alloy"
        tts = openai.TTS(voice=voice, api_key=keys["openai"])
    return stt, tts


# ---------------------------------------------------------------- the call

class PhoneCall:
    """State for one call; bridges LiveKit audio events to conversation_turn_service."""

    def __init__(self, ctx: JobContext, info: dict, caller_identity: str):
        self.ctx = ctx
        self.info = info
        self.call_id: int = info["call_id"]
        self.company_id: int = info["company_id"]
        self.conversation_id: str = info["conversation_id"]
        self.language: str = info["language"]
        self.caller_identity = caller_identity
        self.session: Optional[AgentSession] = None
        self.options: list = []          # pending workflow prompt options (keypad)
        self.waiting_for_human = False
        self.human_joined = asyncio.Event()
        self.ended = asyncio.Event()
        self.lock = asyncio.Lock()       # one turn at a time
        self.digits_cfg: Optional[dict] = None  # keypad collection in progress (get_digits node)
        self.digit_buffer = ""
        self.digits_retries = 0
        self._prompt_items: list = []
        self.hanging_up = False

    async def say(self, items: list):
        """Speak items in order: plain text (TTS) or {"text", "audio_url"} (recorded prompt). Returns the last handle."""
        handle = None
        if self.session is None:
            return None
        for item in items:
            text, audio_url = (item.get("text") or "", item.get("audio_url")) if isinstance(item, dict) else (item or "", None)
            try:
                if audio_url:
                    path = await _fetch_audio(audio_url)
                    if path:
                        from livekit.agents.utils.audio import audio_frames_from_file
                        handle = self.session.say(text or "(recorded prompt)", audio=audio_frames_from_file(path),
                                                  add_to_chat_ctx=False)
                        continue
                if text.strip():
                    handle = self.session.say(text)
            except RuntimeError:
                # audio session already closed (e.g. speech provider failure); call actions still run
                logger.warning(f"[call {self.call_id}] could not speak (audio session closed): {text[:60]!r}")
                return None
        return handle

    async def on_session_closed(self, error) -> None:
        """The AI's audio pipeline died (speech provider down / bad key): don't leave the caller in silence."""
        if self.ended.is_set() or self.human_joined.is_set() or self.hanging_up or self.waiting_for_human:
            return
        from app.core.database import SessionLocal
        from app.services import call_service

        logger.error(f"[call {self.call_id}] AI audio session closed ({error}); handing the caller to a human")
        self.session = None
        await asyncio.to_thread(_db_call, _record, self.call_id, "ai_failed", "system", {"error": str(error)[:500]})
        db = SessionLocal()
        try:
            await call_service.request_human(db, self.conversation_id, reason="AI voice failed")
        finally:
            db.close()
        self.waiting_for_human = True

    async def apply(self, result) -> None:
        """Act on a turn result: speak, then wait for a choice / digits, or run call actions."""
        self.options = result.options if result.expects == "prompt" else []
        self.digits_cfg = result.digits if result.expects == "digits" else None
        self.digit_buffer = ""
        handle = await self.say(result.say)
        if self.digits_cfg:
            self.digits_retries = int(self.digits_cfg.get("retries", 2))
            self._prompt_items = [x for x in result.say][-1:]  # the question, replayed on timeout
            self._arm_digit_timer(handle)
        for action in result.actions:
            if action.get("type") == "transfer_to_agent":
                await self.transfer_to_agents(action)
            elif action.get("type") == "hangup":
                await self.hang_up(handle)
                return
        if result.handoff and not any(a.get("type") == "transfer_to_agent" for a in result.actions):
            if not result.say:
                await self.say([_pick(HOLD, self.language)])
            asyncio.create_task(self.wait_for_human())

    async def run_turn(self, text: str, option_key: Optional[str] = None, save_caller: bool = True) -> None:
        """Caller said something (or pressed keys): ask HeyGenAlly what to say next."""
        from app.core.database import SessionLocal
        from app.models.conversation_session import ConversationSession
        from app.services import conversation_turn_service as turns

        if self.waiting_for_human or self.hanging_up:
            return
        self._cancel_digit_timer()
        async with self.lock:
            db = SessionLocal()
            try:
                conv = db.query(ConversationSession).filter(
                    ConversationSession.conversation_id == self.conversation_id).one()
                if save_caller and text:
                    await turns.save_caller_message(db, conv, text)
                result = await turns.handle_turn(db, conv, text, option_key=option_key, voice_language=self.language)
            finally:
                db.close()
        await self.apply(result)

    async def start(self) -> None:
        """Greeting: the number's entry workflow (IVR), else the Agent's welcome message."""
        from app.core.database import SessionLocal
        from app.models.conversation_session import ConversationSession
        from app.services import conversation_turn_service as turns

        if self.info["entry_workflow_id"]:
            db = SessionLocal()
            try:
                conv = db.query(ConversationSession).filter(
                    ConversationSession.conversation_id == self.conversation_id).one()
                result = await turns.run_workflow(db, conv, self.info["entry_workflow_id"])
            finally:
                db.close()
            await self.apply(result)
            return
        agent = self.info["agent"] or {}
        await self.say([agent.get("welcome_message") or _pick(GREETING, self.language)])

    # ---------------------------------------------------------- keypad

    def on_dtmf(self, dtmf: rtc.SipDTMF) -> None:
        from app.services import conversation_turn_service as turns

        digit = dtmf.digit
        logger.info(f"[call {self.call_id}] DTMF {digit!r}")
        asyncio.create_task(asyncio.to_thread(_db_call, _record, self.call_id, "dtmf", "caller", {"digit": digit}))
        asyncio.create_task(_broadcast(self.company_id, {"type": "phone_call_dtmf", "call_id": self.call_id, "digit": digit}))
        if self.session is not None and self.session.current_speech is not None:
            self.session.current_speech.interrupt()  # a key press cuts the prompt short
        if self.digits_cfg:
            cfg = self.digits_cfg
            if digit == cfg.get("terminator", "#"):
                self._submit_digits()
                return
            self.digit_buffer += digit
            if len(self.digit_buffer) >= int(cfg.get("max_digits", 1)):
                self._submit_digits()
            else:
                self._arm_digit_timer(None)  # inter-digit timeout restarts
            return
        key = turns.option_key_for_digit(self.options, digit)
        if key is not None:
            label = turns._option_label(self.options[int(digit) - 1])
            asyncio.create_task(self._pressed(f"Pressed {digit} ({label})", label, key))

    def _submit_digits(self) -> None:
        digits = self.digit_buffer
        self.digits_cfg, self.digit_buffer = None, ""
        self._cancel_digit_timer()
        asyncio.create_task(self._pressed(f"Entered {digits}" if digits else "No input", digits, None))

    def _arm_digit_timer(self, handle) -> None:
        self._cancel_digit_timer()
        timeout = int((self.digits_cfg or {}).get("timeout_seconds", 6))

        async def timer():
            if handle is not None:
                await handle.wait_for_playout()  # count from the end of the question
            await asyncio.sleep(timeout)
            if not self.digits_cfg:
                return
            if self.digit_buffer or self.digits_retries <= 0:
                self._submit_digits()  # partial entry, or out of retries -> continue with what we have
            else:
                self.digits_retries -= 1
                replay = await self.say(self._prompt_items)
                self._arm_digit_timer(replay)
        self._digit_timer = asyncio.create_task(timer())

    def _cancel_digit_timer(self) -> None:
        task = getattr(self, "_digit_timer", None)
        if task and not task.done() and task is not asyncio.current_task():
            task.cancel()

    async def _pressed(self, caller_text: str, value: str, option_key: Optional[str]) -> None:
        from app.core.database import SessionLocal
        from app.models.conversation_session import ConversationSession
        from app.services import conversation_turn_service as turns

        db = SessionLocal()
        try:
            conv = db.query(ConversationSession).filter(ConversationSession.conversation_id == self.conversation_id).one()
            await turns.save_caller_message(db, conv, caller_text)
        finally:
            db.close()
        await self.run_turn(value, option_key=option_key, save_caller=False)

    # ---------------------------------------------------------- transfers / hang-up

    async def transfer_to_agents(self, action: dict) -> None:
        """IVR transfer node: ring the team, hold the caller; on overflow play the message and hang up."""
        from app.core.database import SessionLocal
        from app.services import call_service

        db = SessionLocal()
        try:
            routed = await call_service.request_human(db, self.conversation_id, reason=action.get("reason", ""),
                                                      team_id=action.get("team_id"), queue_id=action.get("queue_id")) or {}
        finally:
            db.close()
        # node settings win; otherwise the queue's wait limit and overflow message
        asyncio.create_task(self.wait_for_human(
            max_wait=action.get("max_wait_seconds") or routed.get("max_wait_seconds"),
            overflow_text=action.get("overflow_text") or routed.get("overflow_text")))

    async def hang_up(self, after=None) -> None:
        """End the call from the IVR (after the last message finishes playing)."""
        from app.services import call_service

        self.hanging_up = True
        if after is not None:
            await after.wait_for_playout()
        closed = await asyncio.to_thread(_db_call, _finish, self.call_id, "system")
        if closed:
            await _broadcast(self.company_id, {"type": "phone_call_ended", "call": closed})
            await _after_call_ended(self.call_id)
        await call_service.hang_up_room(self.ctx.room.name)

    async def wait_for_human(self, max_wait: Optional[int] = None, overflow_text: Optional[str] = None) -> None:
        """Keep the caller company until an agent joins. Nobody answers: overflow message + hang up, or back to the AI."""
        self.waiting_for_human = True
        deadline = time.monotonic() + (max_wait or settings.TELEPHONY_HANDOFF_WAIT_SECONDS)
        next_say = time.monotonic() + 30
        # queues that announce wait times say position + expected wait straight away
        text, interval = await _waiting_message(self.call_id, self.language, first=False)
        if text != _pick(STILL_HOLDING, self.language):
            await self.say([text])
            next_say = time.monotonic() + interval
        while time.monotonic() < deadline and not self.ended.is_set():
            try:
                await asyncio.wait_for(self.human_joined.wait(),
                                       timeout=max(1, min(next_say, deadline) - time.monotonic()))
                return  # hand_over_to_human takes it from here
            except asyncio.TimeoutError:
                if next_say <= time.monotonic() < deadline:
                    text, interval = await _waiting_message(self.call_id, self.language, first=False)
                    await self.say([text])
                    next_say = time.monotonic() + interval
        if self.ended.is_set() or self.human_joined.is_set():
            return
        await asyncio.to_thread(_db_call, _record, self.call_id, "overflow", "system", {"waited_seconds": max_wait})
        if overflow_text:
            handle = await self.say([overflow_text])
            await self.hang_up(handle)
            return
        await asyncio.to_thread(_db_call, _give_back_to_ai, self.call_id)
        self.waiting_for_human = False
        await self.say([_pick(NO_AGENT, self.language)])

    async def hand_over_to_human(self, identity: str) -> None:
        """A human agent joined the room: the AI stops listening and leaves; the call continues."""
        logger.info(f"[call {self.call_id}] {identity} joined; AI leaving the call")
        self.human_joined.set()
        self.ended.set()
        if self.session is not None:
            await self.session.aclose()
        self.ctx.shutdown(reason="handed over to human agent")


class CallAgent(Agent):
    """No LLM of its own: every finished caller turn is answered by HeyGenAlly's Agent / workflows."""

    def __init__(self, call: PhoneCall):
        super().__init__(instructions="Replies are produced by HeyGenAlly (conversation_turn_service).")
        self.call = call

    async def on_user_turn_completed(self, turn_ctx: llm.ChatContext, new_message: llm.ChatMessage) -> None:
        text = (new_message.text_content or "").strip()
        if text:
            await self.call.run_turn(text)
        raise StopResponse()  # we already spoke (or chose silence); skip LiveKit's own reply


def prewarm(proc: JobProcess):
    """
    Runs once per job process before a call is assigned: imports the backend, loads the VAD model
    and opens a DB connection so callers don't wait for it. Warm processes stay idle until a call.
    """
    t = time.monotonic()
    import app.services.connection_manager  # noqa: F401  (pulls in app.services: workflows, agents, RAG)
    import app.services.call_service  # noqa: F401
    import app.services.conversation_turn_service  # noqa: F401
    from app.core.database import SessionLocal
    from app.models.phone_number import PhoneNumber
    from livekit.plugins import silero

    proc.userdata["vad"] = silero.VAD.load()
    if settings.TELEPHONY_PREWARM_EMBEDDINGS:
        from app.services import vectorization_service
        vectorization_service._get_model()
    db = SessionLocal()
    try:
        db.query(PhoneNumber.id).first()  # configure ORM mappers + open a pooled DB connection
    finally:
        db.close()
    logger.info(f"[prewarm] job process ready in {time.monotonic() - t:.1f}s")


def _wait_estimate(db, call_id: int) -> Optional[dict]:
    from app.services import acd_service
    return acd_service.wait_estimate(db, call_id)


async def _waiting_message(call_id: int, language: str, first: bool) -> tuple[str, int]:
    """What to tell a waiting caller and when to speak next: position + expected wait when the queue
    announces it (FR-CC-013), otherwise the usual hold message every 30 s."""
    try:
        estimate = await asyncio.to_thread(_db_call, _wait_estimate, call_id)
    except Exception:
        logger.exception(f"[call {call_id}] wait estimate failed")
        estimate = None
    if estimate:
        from app.services import acd_service
        return acd_service.wait_message(estimate, language), estimate["interval"]
    return _pick(HOLD if first else STILL_HOLDING, language), 30


def _hold_status(db, call_id: int) -> dict:
    from app.models.voice_call import VoiceCall

    call = db.query(VoiceCall).filter(VoiceCall.id == call_id).first()
    if not call:
        return {"done": True}
    return {"done": call.status not in ("ringing", "in_progress"), "handler": call.handled_by_user_id,
            "on_hold": call.hold_started_at is not None, "language": None}


async def hold_company(ctx: JobContext, meta: dict) -> None:
    """
    "hold" mode: keep a waiting caller company (blind transfer in progress, or agent consulting).
    Leaves when the call ends, or when it has a handler who is in the room and the call isn't on hold.
    """
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
    call_id = meta.get("call_id")
    info_keys = await asyncio.to_thread(_db_call, _speech_keys, meta.get("company_id"))
    session = None
    if info_keys.get("openai"):
        from livekit.plugins import openai
        session = AgentSession(tts=openai.TTS(voice="alloy", api_key=info_keys["openai"]))
        try:
            await session.start(room=ctx.room, agent=Agent(instructions="hold"))
        except Exception:
            logger.exception(f"[hold {call_id}] could not start audio")
            session = None
    language = "en"
    said_at = 0.0
    interval = 0
    first = True
    while True:
        status = await asyncio.to_thread(_db_call, _hold_status, call_id)
        if status["done"]:
            break
        handler_present = status["handler"] and any(
            p.identity == f"user_{status['handler']}" for p in ctx.room.remote_participants.values())
        if handler_present and not status["on_hold"]:
            break
        if session is not None and time.monotonic() - said_at >= interval:
            text, interval = await _waiting_message(call_id, language, first)
            try:
                session.say(text)
            except RuntimeError:
                session = None
            first, said_at = False, time.monotonic()
        await asyncio.sleep(2)
    logger.info(f"[hold {call_id}] leaving")
    if session is not None:
        await session.aclose()
    ctx.shutdown(reason="hold finished")


async def entrypoint(ctx: JobContext):
    meta = json.loads(ctx.job.metadata or "{}")
    room_name = ctx.room.name
    from app.core.redis_client import redis_enabled
    if redis_enabled():
        from app.services.connection_manager import manager
        await manager.start_fanout(settings.WS_FANOUT_CHANNEL, subscribe=False)
    if meta.get("mode") == "hold":
        await hold_company(ctx, meta)
        return

    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
    caller = await ctx.wait_for_participant(kind=rtc.ParticipantKind.PARTICIPANT_KIND_SIP)
    info = await asyncio.to_thread(_db_call, _open_call, meta.get("phone_number_id"), room_name, dict(caller.attributes))
    if info is None:
        logger.error(f"[call] {room_name}: phone number {meta.get('phone_number_id')} not found; leaving")
        ctx.shutdown(reason="unknown number")
        return
    call = PhoneCall(ctx, info, caller.identity)
    logger.info(f"[call {call.call_id}] {info['call']['caller']} -> {info['call']['called']} "
                f"agent={(info['agent'] or {}).get('name')} workflow={info['entry_workflow_id']} lang={call.language}")
    if info["created"]:
        for payload in await asyncio.to_thread(_db_call, _new_call_payloads, call.call_id):
            await _broadcast(call.company_id, payload)
    await _broadcast(call.company_id, {"type": "phone_call_updated", "call": info["call"]})

    def on_participant_connected(p: rtc.RemoteParticipant):
        role = p.attributes.get("agentconnect.role", "agent")
        if p.identity.startswith("user_") and role == "agent" and call.waiting_for_human:
            asyncio.create_task(call.hand_over_to_human(p.identity))

    def on_participant_disconnected(p: rtc.RemoteParticipant):
        if p.identity == caller.identity:
            call.ended.set()

    ctx.room.on("sip_dtmf_received", call.on_dtmf)
    ctx.room.on("participant_connected", on_participant_connected)
    ctx.room.on("participant_disconnected", on_participant_disconnected)

    stt, tts = _build_speech(info)
    if stt is None or tts is None:
        # Without speech keys the AI can't talk: hand the caller straight to a human
        logger.error(f"[call {call.call_id}] no speech-to-text / text-to-speech key (OpenAI or Deepgram); ringing agents")
        from app.core.database import SessionLocal
        from app.services import call_service
        db = SessionLocal()
        try:
            await call_service.request_human(db, call.conversation_id, reason="AI voice unavailable (no speech keys)")
        finally:
            db.close()
        call.waiting_for_human = True
    else:
        call.session = AgentSession(stt=stt, tts=tts, vad=ctx.proc.userdata.get("vad"),
                                    min_endpointing_delay=0.5, max_endpointing_delay=4.0)
        call.session.on("close", lambda ev: asyncio.create_task(call.on_session_closed(ev.error or ev.reason)))
        await call.session.start(room=ctx.room, agent=CallAgent(call))
        await call.start()

    await call.ended.wait()
    if call.human_joined.is_set():
        return  # the human's call continues; the webhook closes the record when it ends
    logger.info(f"[call {call.call_id}] caller hung up")
    closed = await asyncio.to_thread(_db_call, _finish, call.call_id, "caller")
    if closed:  # the webhook may already have closed it
        await _broadcast(call.company_id, {"type": "phone_call_ended", "call": closed})
        await _after_call_ended(call.call_id)
    ctx.shutdown(reason="caller hung up")


if __name__ == "__main__":
    cli.run_app(WorkerOptions(
        entrypoint_fnc=entrypoint,
        prewarm_fnc=prewarm,
        initialize_process_timeout=90,  # prewarm imports the full backend
        num_idle_processes=settings.TELEPHONY_VOICE_IDLE_PROCESSES,
        agent_name=settings.TELEPHONY_VOICE_AGENT_NAME,  # explicit dispatch only (from SIP dispatch rules)
        ws_url=settings.LIVEKIT_URL,
        api_key=settings.LIVEKIT_API_KEY,
        api_secret=settings.LIVEKIT_API_SECRET,
    ))
