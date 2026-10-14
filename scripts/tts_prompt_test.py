"""
Integration test for pre-generated phone prompts (tts_prompt_service) — no phone needed.

1. Fixed texts are found in an IVR workflow + its sub-workflow; {{placeholder}} text and recorded
   prompts (audio_url) are left out.
2. They match exactly what the workflow engine makes the voice process say (prompt + keypad options too),
   including what is said before / inside a sub-workflow.
3. Sync generates each once into MinIO with the Agent's TTS provider + voice, a second sync generates
   nothing, editing a prompt replaces it, changing the Agent's provider regenerates everything.
4. The voice process finds the stored file for fixed text (and decodes it), and live speech for the rest;
   live speech goes through the shared TTSService (ProviderTTS adapter).

Uses a temporary company (agent, workflows, number, sessions) and removes everything afterwards.
Text-to-speech is stubbed with a generated tone unless --live (then the Agent's provider is really called:
--provider / --voice, default voice_engine / default).
Run from backend/:  python -m scripts.tts_prompt_test [--live [--provider openai --voice nova]]
"""
import argparse
import asyncio
import io
import json
import math
import struct
import sys
import uuid
import wave

from app.core.database import SessionLocal
from app.core.object_storage import BUCKET_NAME, s3_client
from app.models.agent import Agent
from app.models.chat_message import ChatMessage
from app.models.company import Company
from app.models.contact_center import TtsPrompt
from app.models.conversation_session import ConversationSession
from app.models.memory import Memory
from app.models.phone_number import PhoneNumber
from app.models.workflow import Workflow
from app.services import conversation_turn_service as turns
from app.services import tts_prompt_service as tts

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--live", action="store_true", help="call the real TTS provider instead of a stub")
parser.add_argument("--provider", default="voice_engine", choices=["voice_engine", "localai", "openai", "groq"])
parser.add_argument("--voice", default="default")
args = parser.parse_args()

SUB = {"nodes": [
    {"id": "start", "type": "start", "data": {}},
    {"id": "note", "type": "response", "data": {"output_value": "Calls may be recorded for quality."}},
], "edges": [{"id": "e1", "source": "start", "target": "note"}]}


def ivr(sub_id: int, welcome: str) -> dict:
    return {"nodes": [
        {"id": "start", "type": "start", "data": {}},
        {"id": "welcome", "type": "response", "data": {"output_value": welcome}},
        {"id": "sub", "type": "subworkflow", "data": {"subworkflow_id": sub_id}},
        {"id": "menu", "type": "prompt", "data": {"params": {
            "prompt_text": "Which department do you need?",
            "options": [{"key": "report", "value": "Report"}, {"key": "status", "value": "Case status"}]}}},
        {"id": "pin", "type": "get_digits", "data": {"params": {
            "prompt_text": "Enter your case number, then press hash.", "max_digits": 6, "save_to_variable": "ref"}}},
        {"id": "recorded", "type": "play_audio", "data": {"params": {
            "text": "This one is a recording.", "audio_url": "https://example.invalid/rec.wav"}}},
        {"id": "transfer", "type": "transfer_to_agent", "data": {"params": {
            "text": "Connecting you about case {{context.ref}}.", "overflow_text": "Please call again later."}}},
        {"id": "closed", "type": "hangup", "data": {"params": {"text": "We are closed. Goodbye."}}},
        {"id": "ask", "type": "listen", "data": {"params": {"question_text": "Please describe the issue."}}},
    ], "edges": [
        {"id": "e1", "source": "start", "target": "welcome"},
        {"id": "e2", "source": "welcome", "target": "sub"},
        {"id": "e3", "source": "sub", "target": "menu"},
        {"id": "e4", "source": "menu", "target": "pin"},
        {"id": "e5", "source": "pin", "target": "transfer"},
    ]}


failures = []


def check(name, condition, detail=""):
    print(f"  {'ok  ' if condition else 'FAIL'} {name}{(' -> ' + str(detail)) if detail and not condition else ''}")
    if not condition:
        failures.append(name)


def tone_wav() -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        w.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * i / 16000)))
                               for i in range(8000)))
    return buf.getvalue()


async def main():
    from app.agents.contact_center_agent import _stored_prompt

    db = SessionLocal()
    tag = uuid.uuid4().hex[:8]
    company = Company(name=f"__tts_prompt_test_{tag}")
    db.add(company); db.commit(); db.refresh(company)
    cid = company.id
    provider, voice = (args.provider, args.voice) if args.live else ("openai", "nova")
    agent = Agent(name="TTS test agent", company_id=cid, tts_provider=provider, voice_id=voice, language="en",
                  welcome_message="Welcome to the test agent.")
    sub = Workflow(name=f"__tts_sub_{tag}", company_id=cid, visual_steps=json.dumps(SUB), steps={}, is_active=False, version=1)
    db.add_all([agent, sub]); db.commit(); db.refresh(sub)
    wf = Workflow(name=f"__tts_ivr_{tag}", company_id=cid, visual_steps=json.dumps(ivr(sub.id, "Welcome to the test line.")),
                  steps={}, is_active=False, version=1)
    db.add(wf); db.commit(); db.refresh(wf); db.refresh(agent)
    phone = PhoneNumber(company_id=cid, number=f"tts{tag}", provider="livekit_sip", routing_mode="ai", language="en",
                        entry_workflow_id=wf.id, default_agent_id=agent.id, provider_config={})
    db.add(phone); db.commit()

    calls = []
    from app.services.tts_service import TTSService
    original_stream = TTSService.text_to_speech_stream
    if not args.live:
        async def fake_stream(self, text, voice_id, provider_):
            calls.append((provider_, voice_id, text))
            data = tone_wav()
            for i in range(0, len(data), 4096):
                yield data[i:i + 4096]
        TTSService.text_to_speech_stream = fake_stream
    sessions = []
    try:
        print("1. Fixed texts in the IVR workflow")
        texts = tts.workflow_texts(db, wf.id, cid)
        expected = {
            "Welcome to the test line.", "Calls may be recorded for quality.",
            "Which department do you need? Press 1 for Report, 2 for Case status.",
            "Enter your case number, then press hash.", "Please call again later.",
            "We are closed. Goodbye.", "Please describe the issue.",
        }
        check("all fixed texts found (incl. sub-workflow)", texts == expected, sorted(texts ^ expected))
        check("{{placeholder}} text left out", not any("{{" in t or "case 1" in t for t in texts))
        check("recorded prompt (audio_url) left out", "This one is a recording." not in texts)

        print("2. Same text the engine makes the voice process say")
        conv = ConversationSession(conversation_id=f"tts_test_{tag}", company_id=cid, channel="voice",
                                   agent_id=agent.id, status="active", is_ai_enabled=True)
        db.add(conv); db.commit(); db.refresh(conv); sessions.append(conv)
        out = await turns.run_workflow(db, conv, wf.id)
        spoken = [s for s in out.say if isinstance(s, str)]
        print("   says:", spoken)
        check("what comes before / inside the sub-workflow is spoken", spoken[:2] == [
            "Welcome to the test line.", "Calls may be recorded for quality."], spoken)
        check("every spoken line has a stored prompt", spoken and all(s in texts for s in spoken), [s for s in spoken if s not in texts])
        out = await turns.handle_turn(db, conv, "Case status", option_key="status")
        out = await turns.handle_turn(db, conv, "123456")
        dynamic = [s for s in out.say if isinstance(s, str) and "123456" in s]
        check("per-call text spoken but not stored", dynamic and not (set(dynamic) & texts), out.say)

        print("3. Sync into MinIO")
        wanted = tts.desired_prompts(db, cid)
        check("Agent's provider + voice used", {(w["provider"], w["voice"]) for w in wanted.values()} == {(provider, voice)},
              {(w["provider"], w["voice"]) for w in wanted.values()})
        check("greeting / hold phrases + welcome included",
              all(any(w["text"] == t for w in wanted.values()) for t in
                  (tts.GREETING["en"], tts.HOLD["en"], "Welcome to the test agent.")))
        s1 = await tts.sync_company(cid)
        print("   first sync:", s1)
        check("every prompt generated once", s1["generated"] == s1["total"] == len(wanted) and s1["failed"] == 0, s1)
        rows = db.query(TtsPrompt).filter(TtsPrompt.company_id == cid).all()
        check("rows ready with files", rows and all(r.status == "ready" and r.object_key for r in rows))
        head = s3_client.head_object(Bucket=BUCKET_NAME, Key=rows[0].object_key)
        check("file is in MinIO", head["ContentLength"] > 0)
        check("generated through TTSService with the Agent's provider", args.live or all(
            c[:2] == (provider, voice) for c in calls), calls[:2])
        n_calls = len(calls)
        s2 = await tts.sync_company(cid)
        check("second sync generates nothing", s2["generated"] == 0 and s2["removed"] == 0 and len(calls) == n_calls, s2)

        wf.visual_steps = json.dumps(ivr(sub.id, "Welcome to the new test line."))
        db.commit()
        old_key = tts.cache_key(provider, voice, "Welcome to the test line.")
        old_obj = next(r.object_key for r in rows if r.key == old_key)
        s3 = await tts.sync_company(cid)
        print("   after edit:", s3)
        check("edited prompt: one new, one removed", s3["generated"] == 1 and s3["removed"] == 1, s3)
        try:
            s3_client.head_object(Bucket=BUCKET_NAME, Key=old_obj)
            check("old file deleted from MinIO", False)
        except Exception:
            check("old file deleted from MinIO", True)

        print("4. Voice process playback")
        speech = {"provider": provider, "voice": voice}
        prompts = tts.ready_map(db, cid, provider, voice)
        path = await _stored_prompt(prompts, speech, "Welcome to the new test line.")
        check("fixed text -> local stored file", bool(path), path)
        other = {"provider": "localai" if provider != "localai" else "openai", "voice": voice}
        check("other provider -> live speech", await _stored_prompt(
            tts.ready_map(db, cid, other["provider"], voice), other, "Welcome to the new test line.") is None)
        check("per-call text -> live speech", await _stored_prompt(prompts, speech, "Connecting you about case 123456.") is None)
        if path:
            from livekit.agents.utils.audio import audio_frames_from_file
            frames = [f async for f in audio_frames_from_file(path)]
            seconds = sum(f.samples_per_channel for f in frames) / 48000
            check("file decodes to audio", seconds > 0.2, seconds)

        from app.agents.provider_tts import ProviderTTS
        live = ProviderTTS(provider, voice, {})
        frame = await live.synthesize("Connecting you about case 123456.").collect()
        await live.aclose()
        check("live speech through TTSService decodes", frame.duration > 0.2, frame.duration)

        print("5. Agent's provider changed -> prompts regenerated with it")
        agent.tts_provider = "localai" if provider != "localai" else "voice_engine"
        db.commit()
        s5 = await tts.sync_company(cid)
        print("   after provider change:", s5)
        check("all regenerated, old removed", s5["generated"] == s5["total"] and s5["removed"] == s5["total"], s5)
        st = tts.status(db, cid)
        check("status shows the number's provider", st["numbers"] and st["numbers"][0]["provider"] == agent.tts_provider
              and st["numbers"][0]["ready"] == s5["total"], st["numbers"])

        print("6. Number removed -> prompts removed")
        db.delete(phone); db.commit(); phone = None
        s4 = await tts.sync_company(cid)
        check("everything cleaned up", s4["total"] == 0 and db.query(TtsPrompt).filter(TtsPrompt.company_id == cid).count() == 0, s4)
    finally:
        TTSService.text_to_speech_stream = original_stream
        db.rollback()
        objs = [r.object_key for r in db.query(TtsPrompt).filter(TtsPrompt.company_id == cid) if r.object_key]
        if objs:
            tts._delete(objs)
        db.query(TtsPrompt).filter(TtsPrompt.company_id == cid).delete()
        for conv in sessions:
            db.query(ChatMessage).filter(ChatMessage.session_id == conv.id).delete()
            db.query(Memory).filter(Memory.session_id == conv.conversation_id).delete(synchronize_session=False)
            db.delete(conv)
        if phone is not None:
            db.delete(phone)
        db.flush()
        db.delete(wf); db.delete(sub); db.flush()
        db.delete(agent); db.flush()
        db.delete(company)
        db.commit(); db.close()

    print("\nRESULT", "PASS" if not failures else f"FAIL ({len(failures)}): {failures}")
    sys.exit(1 if failures else 0)


asyncio.run(main())
