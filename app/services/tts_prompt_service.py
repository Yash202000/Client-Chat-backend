"""
Pre-generated speech for fixed phone prompts.

IVR text rarely changes once a workflow is set up, so instead of calling text-to-speech on every call,
the fixed texts a caller can hear are generated once and stored in MinIO / S3:
  - phone-related node text in a number's entry workflow (and its sub-workflows): response, play_audio,
    transfer_to_agent (+ overflow text), hangup, listen question, get_digits prompt, prompt + its
    keypad options ("... Press 1 for Sales, 2 for Support.")
  - the Agent's welcome message and the voice process's own phrases (greeting, hold, still holding, no agent)

Speech comes from the number's Agent: its TTS provider + voice (Agent settings → Voice Configuration),
through the shared TTSService (openai / localai / voice_engine), the same as live call speech. Numbers
without an Agent use TELEPHONY_TTS_DEFAULT_PROVIDER.

Entries are keyed by sha256(provider|voice|text): editing a prompt or changing the Agent's provider or
voice creates a new entry and the old one is removed on the next sync. Text containing {{placeholders}} is
never stored (it differs per call and may contain personal data); nor are AI replies. Recorded prompts
(audio_url) always win and need nothing from here.

sync_company() runs after workflows, numbers or agents change (background task) and from
scripts/tts_prompt_sync.py. The voice process loads ready_map() at call start and plays a stored file
when the exact text has one, otherwise it falls back to live text-to-speech.
"""
import asyncio
import hashlib
import logging
import os
import tempfile
from typing import Optional

from sqlalchemy.orm import Session

from app.core.config import settings

logger = logging.getLogger(__name__)

OBJECT_PREFIX = "tts-prompts"
HOLD_LANGUAGE = "en"       # hold mode (blind transfer) speaks English
PROVIDERS = ("voice_engine", "localai", "openai", "groq")  # what TTSService supports
OPENAI_VOICES = ("alloy", "echo", "fable", "onyx", "nova", "shimmer")  # OpenAITTSService's voices
STT_PROVIDERS = ("deepgram", "openai", "groq", "localai")  # what the voice process can listen with
GROQ_VOICES_EN = ("troy", "austin", "daniel", "autumn", "diana", "hannah")  # Orpheus English (checked 14 Oct 2026)

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
SYSTEM_PHRASES = (GREETING, HOLD, STILL_HOLDING, NO_AGENT)

_GENERATE_CONCURRENCY = 4
_company_locks: dict[int, asyncio.Lock] = {}
_cache_dir: Optional[str] = None


def lang(code: Optional[str]) -> str:
    return (code or "en").split("-")[0].lower()


def pick(texts: dict, language: str) -> str:
    return texts.get(lang(language), texts["en"])


def speech_profile(db: Session, phone) -> dict:
    """Which provider / voice / language a number's calls speak and listen with (its Agent's voice settings)."""
    from app.models.agent import Agent

    agent = db.query(Agent).filter(Agent.id == phone.default_agent_id).first() if phone.default_agent_id else None
    provider = (agent.tts_provider if agent else None) or settings.TELEPHONY_TTS_DEFAULT_PROVIDER
    return {
        "provider": provider,
        "voice": (agent.voice_id if agent else None) or "default",
        "stt_provider": (agent.stt_provider if agent else None) or settings.TELEPHONY_STT_DEFAULT_PROVIDER,
        "language": lang(phone.language or (agent.language if agent else None)),
        "agent": agent,
    }


def cache_key(provider: str, voice: str, text: str) -> str:
    raw = f"{provider}|{voice}|{(text or '').strip()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def sniff_audio(data: bytes) -> tuple[str, str]:
    """(mime type, file extension) of encoded audio; providers return mp3, wav or ogg."""
    head = data[:12]
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "audio/wav", ".wav"
    if head[:4] == b"OggS":
        return "audio/ogg", ".ogg"
    if head[:4] == b"fLaC":
        return "audio/flac", ".flac"
    return "audio/mpeg", ".mp3"  # ID3 tag or bare MPEG frames


def is_static(text) -> bool:
    return isinstance(text, str) and bool(text.strip()) and "{{" not in text


def speech_keys(db: Session, company_id: int) -> dict:
    """Company credentials (vault) first, then system keys from settings."""
    from app.services import credential_service

    keys = {}
    for service in ("openai", "deepgram", "groq"):
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
    if not keys.get("groq") and settings.GROQ_API_KEY:
        keys["groq"] = settings.GROQ_API_KEY
    return {k: v for k, v in keys.items() if v}


def stt_available(provider: str, keys: dict) -> bool:
    """Can calls listen with this provider? LocalAI needs no key; the others need theirs."""
    return provider == "localai" or bool(keys.get(provider))


# ---------------------------------------------------------------- which texts are fixed

def _manual_options(params: dict) -> Optional[list]:
    """Prompt node options as the engine builds them in manual mode; None when they come from a variable."""
    if params.get("options_mode", "manual") == "variable":
        return None
    options = params.get("options", [])
    if isinstance(options, str):
        return [{"key": o.strip(), "value": o.strip()} for o in options.split(",") if o.strip()]
    if isinstance(options, list):
        return [o if isinstance(o, dict) and "key" in o and "value" in o else {"key": str(o), "value": str(o)}
                for o in options]
    return []


def _node_texts(node: dict) -> list[str]:
    """Exactly what the voice process would speak for this node, when it doesn't depend on the call."""
    from app.services.conversation_turn_service import speakable_prompt

    node_type, data = node.get("type"), node.get("data") or {}
    params = data.get("params") or {}
    texts = []
    if node_type == "response":
        texts.append(data.get("output_value"))
    elif node_type in ("play_audio", "transfer_to_agent", "hangup"):
        if not params.get("audio_url"):
            texts.append(params.get("text"))
        if node_type == "transfer_to_agent":
            texts.append(params.get("overflow_text"))
    elif node_type == "listen":
        texts.append(params.get("question_text"))
    elif node_type == "get_digits":
        if not params.get("audio_url"):
            texts.append(params.get("prompt_text"))
    elif node_type == "prompt":
        prompt_text = params.get("prompt_text", "Please provide input.")
        options = _manual_options(params)
        if is_static(prompt_text) and options is not None and not any(
                "{{" in str(o.get("value", "")) for o in options):
            texts.append(speakable_prompt(prompt_text, options))
    return [t for t in texts if is_static(t)]


def _nodes(workflow) -> list[dict]:
    steps = workflow.visual_steps
    if isinstance(steps, str):
        import json
        try:
            steps = json.loads(steps)
        except ValueError:
            return []
    return (steps or {}).get("nodes", []) if isinstance(steps, dict) else []


def workflow_texts(db: Session, workflow_id: int, company_id: int, _seen: Optional[set] = None) -> set[str]:
    """Fixed texts of a workflow and the sub-workflows it calls."""
    from app.services import workflow_service

    seen = _seen if _seen is not None else set()
    if not workflow_id or workflow_id in seen:
        return set()
    seen.add(workflow_id)
    workflow = workflow_service.get_workflow(db, workflow_id, company_id)
    if not workflow:
        return set()
    texts: set[str] = set()
    for node in _nodes(workflow):
        texts.update(_node_texts(node))
        if node.get("type") == "subworkflow":
            texts |= workflow_texts(db, (node.get("data") or {}).get("subworkflow_id"), company_id, seen)
    return texts


def desired_prompts(db: Session, company_id: int) -> dict[str, dict]:
    """Every fixed prompt the company's numbers can play: {key: {text, provider, voice, language}}."""
    from app.models.phone_number import PhoneNumber

    phones = db.query(PhoneNumber).filter(PhoneNumber.company_id == company_id, PhoneNumber.is_active.is_(True)).all()
    wanted: dict[str, dict] = {}

    def add(profile: dict, language: str, text: str):
        if is_static(text):
            wanted.setdefault(cache_key(profile["provider"], profile["voice"], text), {
                "text": text.strip(), "provider": profile["provider"], "voice": profile["voice"], "language": language})

    for phone in phones:
        profile = speech_profile(db, phone)
        # any number can have a blind transfer -> hold mode
        for phrases in (HOLD, STILL_HOLDING):
            add(profile, HOLD_LANGUAGE, pick(phrases, HOLD_LANGUAGE))
        if phone.routing_mode != "ai":
            continue
        language, agent = profile["language"], profile["agent"]
        for phrases in SYSTEM_PHRASES:
            add(profile, language, pick(phrases, language))
        if agent and agent.welcome_message:
            add(profile, language, agent.welcome_message)
        for text in workflow_texts(db, phone.entry_workflow_id, company_id):
            add(profile, language, text)
    return wanted


# ---------------------------------------------------------------- generation + storage

async def synthesize(provider: str, voice: str, text: str, keys: dict) -> bytes:
    """Speech for text from the provider (shared TTSService). Raises when the provider returns nothing."""
    from app.services.tts_service import TTSService

    service = TTSService(openai_api_key=keys.get("openai"), groq_api_key=keys.get("groq"))
    try:
        chunks = [chunk async for chunk in service.text_to_speech_stream(text, voice, provider)]
    finally:
        await service.close()
    audio = b"".join(chunks)
    if not audio:  # TTSService logs and swallows provider errors
        reason = service.groq_service.last_error if provider == "groq" else None
        raise RuntimeError(f"{provider} text-to-speech returned no audio: "
                           f"{reason or 'provider down or key invalid?'}")
    return audio


def _put(company_id: int, key: str, data: bytes) -> str:
    from app.core.object_storage import BUCKET_NAME, s3_client
    mime, ext = sniff_audio(data)
    object_key = f"{OBJECT_PREFIX}/{company_id}/{key}{ext}"
    s3_client.put_object(Bucket=BUCKET_NAME, Key=object_key, Body=data, ContentType=mime)
    return object_key


def _delete(object_keys: list[str]) -> None:
    from app.core.object_storage import BUCKET_NAME, s3_client
    for i in range(0, len(object_keys), 1000):
        chunk = object_keys[i:i + 1000]
        try:
            s3_client.delete_objects(Bucket=BUCKET_NAME, Delete={"Objects": [{"Key": k} for k in chunk], "Quiet": True})
        except Exception:
            logger.exception("[tts] could not delete old prompt files")


async def sync_company(company_id: int, regenerate_failed: bool = True) -> dict:
    """
    Make the stored prompts match what the company's numbers can play: add new ones, generate missing
    audio, remove ones no longer used. Safe to call often; only new / changed texts cost anything.
    """
    from app.core.database import SessionLocal
    from app.models.contact_center import TtsPrompt

    lock = _company_locks.setdefault(company_id, asyncio.Lock())
    async with lock:
        db = SessionLocal()
        try:
            wanted = desired_prompts(db, company_id)
            rows = {r.key: r for r in db.query(TtsPrompt).filter(TtsPrompt.company_id == company_id).all()}

            stale = [r for k, r in rows.items() if k not in wanted]
            removed_objects = [r.object_key for r in stale if r.object_key]
            for r in stale:
                db.delete(r)
            for key, item in wanted.items():
                if key not in rows:
                    rows[key] = TtsPrompt(company_id=company_id, key=key, text=item["text"], voice=item["voice"],
                                          provider=item["provider"], language=item["language"], status="pending")
                    db.add(rows[key])
            db.commit()
            if removed_objects:
                await asyncio.to_thread(_delete, removed_objects)

            todo = [r for k, r in rows.items() if k in wanted and (
                r.status == "pending" or (regenerate_failed and r.status == "failed"))]
            summary = {"company_id": company_id, "total": len(wanted), "removed": len(stale),
                       "generated": 0, "failed": 0, "error": None}
            if not todo:
                return summary
            keys = speech_keys(db, company_id)
            sem = asyncio.Semaphore(_GENERATE_CONCURRENCY)

            async def generate(row: TtsPrompt) -> tuple[TtsPrompt, Optional[bytes], Optional[str], Optional[str]]:
                async with sem:
                    try:
                        audio = await synthesize(row.provider, row.voice, row.text, keys)
                        object_key = await asyncio.to_thread(_put, company_id, row.key, audio)
                        return row, audio, object_key, None
                    except Exception as e:
                        logger.warning(f"[tts] company {company_id}: could not generate {row.text[:50]!r} "
                                       f"({row.provider}/{row.voice}): {e}")
                        return row, None, None, str(e)[:500]

            for row, audio, object_key, error in await asyncio.gather(*(generate(r) for r in todo)):
                if audio is not None:
                    if row.object_key and row.object_key != object_key:
                        removed_objects.append(row.object_key)
                    row.status, row.error = "ready", None
                    row.object_key, row.size_bytes = object_key, len(audio)
                    summary["generated"] += 1
                else:
                    row.status, row.error = "failed", error
                    summary["failed"] += 1
            db.commit()
            logger.info(f"[tts] company {company_id}: {summary}")
            return summary
        finally:
            db.close()


async def sync_company_safe(company_id: int) -> None:
    """Background-task entry point: never raises."""
    if not settings.TELEPHONY_TTS_CACHE:
        return
    try:
        await sync_company(company_id)
    except Exception:
        logger.exception(f"[tts] prompt sync failed for company {company_id}")


def status(db: Session, company_id: int) -> dict:
    """Per number: which provider / voice its calls use, and how many of its prompts are stored."""
    from app.models.contact_center import TtsPrompt
    from app.models.phone_number import PhoneNumber

    rows = db.query(TtsPrompt).filter(TtsPrompt.company_id == company_id).all()
    keys = speech_keys(db, company_id)
    numbers = []
    for phone in db.query(PhoneNumber).filter(PhoneNumber.company_id == company_id).order_by(PhoneNumber.number):
        profile = speech_profile(db, phone)
        agent = profile["agent"]
        mine = [r for r in rows if r.provider == profile["provider"] and r.voice == profile["voice"]]
        numbers.append({
            "phone_number_id": phone.id, "number": phone.number, "routing_mode": phone.routing_mode,
            "is_active": phone.is_active, "language": profile["language"],
            "agent": {"id": agent.id, "name": agent.name} if agent else None,
            "provider": profile["provider"], "voice": profile["voice"],
            "stt_provider": profile["stt_provider"], "stt_available": stt_available(profile["stt_provider"], keys),
            "ready": sum(r.status == "ready" for r in mine), "pending": sum(r.status == "pending" for r in mine),
            "failed": sum(r.status == "failed" for r in mine),
        })
    return {
        "enabled": settings.TELEPHONY_TTS_CACHE,
        "default_provider": settings.TELEPHONY_TTS_DEFAULT_PROVIDER,
        "providers": list(PROVIDERS),
        "stt_providers": list(STT_PROVIDERS),
        "openai_voices": list(OPENAI_VOICES),
        "groq_voices": list(GROQ_VOICES_EN),
        "ready": sum(r.status == "ready" for r in rows), "pending": sum(r.status == "pending" for r in rows),
        "failed": sum(r.status == "failed" for r in rows),
        "numbers": numbers,
        "failures": [{"text": r.text, "provider": r.provider, "voice": r.voice, "error": r.error}
                     for r in rows if r.status == "failed"][:20],
    }


async def preview(db: Session, company_id: int, provider: str, voice: str, text: str) -> tuple[bytes, str]:
    """Speak a sample with a provider / voice so admins can check it before saving. (audio, mime)"""
    audio = await synthesize(provider, voice or "default", text, speech_keys(db, company_id))
    return audio, sniff_audio(audio)[0]


# ---------------------------------------------------------------- playback (voice process)

def ready_map(db: Session, company_id: int, provider: str, voice: str) -> dict[str, str]:
    """{cache key: object key} of the stored prompts a call with this provider / voice can play."""
    from app.models.contact_center import TtsPrompt

    if not settings.TELEPHONY_TTS_CACHE:
        return {}
    rows = db.query(TtsPrompt.key, TtsPrompt.object_key).filter(
        TtsPrompt.company_id == company_id, TtsPrompt.provider == provider, TtsPrompt.voice == voice,
        TtsPrompt.status == "ready").all()
    return {k: o for k, o in rows if o}


def local_file(object_key: str) -> Optional[str]:
    """Download a stored prompt once to a local cache file (blocking; run in a thread)."""
    from app.core.object_storage import BUCKET_NAME, s3_client

    global _cache_dir
    if _cache_dir is None:
        _cache_dir = os.path.join(tempfile.gettempdir(), "agentconnect-tts-prompts")
        os.makedirs(_cache_dir, exist_ok=True)
    path = os.path.join(_cache_dir, os.path.basename(object_key))
    if os.path.exists(path):
        return path
    try:
        part = f"{path}.{os.getpid()}.part"  # several voice processes may fetch the same prompt
        s3_client.download_file(BUCKET_NAME, object_key, part)
        os.replace(part, path)
        return path
    except Exception:
        logger.exception(f"[tts] could not fetch stored prompt {object_key}")
        return None
