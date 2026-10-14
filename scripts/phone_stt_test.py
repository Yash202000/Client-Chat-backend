"""
Speech-to-text check for phone calls: the voice process listens with the number's Agent stt_provider.

Speaks a sentence with a TTS provider (TTSService), feeds the audio to the same STT the voice process
builds (_build_stt) and checks the words come back. Also checks that a provider without a key gives
"keypad only" (no STT) instead of failing the call.

Run from backend/:
    python -m scripts.phone_stt_test                              # groq + localai
    python -m scripts.phone_stt_test --stt groq deepgram --tts localai
"""
import argparse
import asyncio
import io
import re
import sys
import wave

from livekit import rtc
from livekit.agents.utils import http_context

from app.agents.contact_center_agent import _build_stt
from app.core.database import SessionLocal
from app.services import tts_prompt_service
from app.services.tts_prompt_service import stt_available, synthesize

SENTENCE = "I would like to check the status of my case please."


def wav_frame(data: bytes) -> rtc.AudioFrame:
    with wave.open(io.BytesIO(data)) as w:
        if w.getsampwidth() != 2:
            raise ValueError(f"expected 16-bit wav, got {w.getsampwidth() * 8}-bit")
        return rtc.AudioFrame(data=w.readframes(w.getnframes()), sample_rate=w.getframerate(),
                              num_channels=w.getnchannels(), samples_per_channel=w.getnframes())


def words(text: str) -> set[str]:
    return set(re.findall(r"[a-z]+", text.lower()))


async def check(provider: str, frame: rtc.AudioFrame, keys: dict) -> bool:
    if not stt_available(provider, keys):
        print(f"  {provider:<9} SKIP  no key (calls on this provider run keypad only)")
        return True
    stt = _build_stt(provider, "en", keys)
    try:
        event = await stt.recognize(frame, language="en")
        text = event.alternatives[0].text if event.alternatives else ""
    except Exception as e:
        print(f"  {provider:<9} FAIL  {type(e).__name__}: {e}")
        return False
    finally:
        await stt.aclose()
    overlap = len(words(text) & words(SENTENCE)) / len(words(SENTENCE))
    ok = overlap >= 0.7
    print(f"  {provider:<9} {'PASS' if ok else 'FAIL'}  heard {text!r} ({overlap:.0%} of the words)")
    return ok


async def main(stt_providers: list[str], tts_provider: str, company_id: int) -> int:
    db = SessionLocal()
    try:
        keys = tts_prompt_service.speech_keys(db, company_id)
    finally:
        db.close()

    http_context._new_session_ctx()  # plugins such as Deepgram use the worker's HTTP session
    results = []
    # A provider without a key -> no STT, so the call stays up keypad-only
    missing = _build_stt("openai", "en", {}) is None and _build_stt("groq", "en", {}) is None
    print(f"  missing key -> keypad only: {'PASS' if missing else 'FAIL'}")
    results.append(missing)
    unknown = _build_stt("nonsense", "en", keys) is None
    print(f"  unknown provider -> keypad only: {'PASS' if unknown else 'FAIL'}")
    results.append(unknown)

    print(f"speaking the test sentence with {tts_provider} …")
    audio = await synthesize(tts_provider, "default", SENTENCE, keys)
    if tts_prompt_service.sniff_audio(audio)[0] != "audio/wav":
        print(f"  {tts_provider} returned {tts_prompt_service.sniff_audio(audio)[0]}; pick a TTS provider that returns wav")
        return 1
    frame = wav_frame(audio)
    print(f"  {frame.duration:.1f}s of audio at {frame.sample_rate} Hz")
    for provider in stt_providers:
        results.append(await check(provider, frame, keys))
    await http_context._close_http_ctx()
    print("ALL PASS" if all(results) else "SOME CHECKS FAILED")
    return 0 if all(results) else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stt", nargs="+", default=["groq", "localai"], choices=list(tts_prompt_service.STT_PROVIDERS))
    parser.add_argument("--tts", default="localai", help="TTS provider used to make the test audio (must return wav)")
    parser.add_argument("--company-id", type=int, default=1, help="company whose vault keys are used")
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.stt, args.tts, args.company_id)))
