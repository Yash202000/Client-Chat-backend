import asyncio

import aiohttp
from typing import AsyncGenerator
import os
import logging
logger = logging.getLogger(__name__)

# --- OpenAI TTS Configuration ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_TTS_URL = "https://api.openai.com/v1/audio/speech"

# --- Service for our custom Voice Engine ---
VOICE_ENGINE_URL = os.getenv("VOICE_ENGINE_URL", "http://voice-engine-service:8001/api/v1/synthesize")

class VoiceEngineTTSService:
    async def text_to_speech_stream(self, text: str, voice_id: str, session: aiohttp.ClientSession) -> AsyncGenerator[bytes, None]:
        headers = { "Content-Type": "application/json" }
        data = { "text": text, "voice_id": voice_id }
        try:
            async with session.post(VOICE_ENGINE_URL, json=data, headers=headers) as response:
                response.raise_for_status()
                async for chunk in response.content.iter_any():
                    yield chunk
        except Exception as e:
            logger.exception(e)

# --- Service for Local AI ---
LOCALAI_TTS_URL = os.getenv("LOCALAI_TTS_URL", "http://localhost:8082/tts")

class LocalAITTSService:
    async def text_to_speech_stream(self, text: str, voice_id: str, session: aiohttp.ClientSession) -> AsyncGenerator[bytes, None]:
        headers = { "Content-Type": "application/json" }
        data = { "model": "voice-en-us-ryan-medium", "input": text, "voice": voice_id }
        try:
            async with session.post(LOCALAI_TTS_URL, json=data, headers=headers) as response:
                response.raise_for_status()
                async for chunk in response.content.iter_any():
                    yield chunk
        except Exception as e:
            logger.exception(e)


# --- Service for OpenAI TTS ---
class OpenAITTSService:
    """OpenAI Text-to-Speech service using the audio/speech endpoint."""

    # Available OpenAI voices: alloy, echo, fable, onyx, nova, shimmer
    DEFAULT_VOICE = "alloy"

    def __init__(self, api_key: str = None):
        self.api_key = api_key or OPENAI_API_KEY

    async def text_to_speech_stream(self, text: str, voice_id: str, session: aiohttp.ClientSession) -> AsyncGenerator[bytes, None]:
        """
        Convert text to speech using OpenAI's TTS API.

        Args:
            text: The text to convert to speech
            voice_id: OpenAI voice name (alloy, echo, fable, onyx, nova, shimmer)
            session: aiohttp client session
        """
        if not self.api_key:
            return

        # Map common voice IDs or use the provided one
        # If voice_id is 'default' or not a valid OpenAI voice, use alloy
        valid_voices = ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]
        voice = voice_id if voice_id in valid_voices else self.DEFAULT_VOICE

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        data = {
            "model": "tts-1",  # Use tts-1 for lower latency, tts-1-hd for higher quality
            "input": text,
            "voice": voice,
            "response_format": "mp3"  # mp3 is widely supported
        }

        try:
            async with session.post(OPENAI_TTS_URL, json=data, headers=headers) as response:
                response.raise_for_status()
                async for chunk in response.content.iter_any():
                    yield chunk
        except aiohttp.ClientResponseError as e:
            logger.exception(e)
        except Exception as e:
            logger.exception(e)

    async def text_to_speech_pcm(
        self,
        text: str,
        voice: str = "alloy"
    ) -> bytes:
        """
        Convert text to raw PCM audio bytes for Twilio streaming.
        OpenAI TTS returns 24kHz 16-bit mono PCM when response_format is "pcm".

        Args:
            text: Text to convert to speech
            voice: OpenAI voice name (alloy, echo, fable, onyx, nova, shimmer)

        Returns:
            Raw PCM 16-bit 24kHz mono audio bytes
        """
        if not self.api_key:
            raise ValueError("OpenAI API key not configured for TTS")

        valid_voices = ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]
        voice = voice if voice in valid_voices else self.DEFAULT_VOICE

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        data = {
            "model": "tts-1",
            "input": text,
            "voice": voice,
            "response_format": "pcm"  # Raw PCM output at 24kHz
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(OPENAI_TTS_URL, json=data, headers=headers) as response:
                response.raise_for_status()
                return await response.read()


# --- Service for Groq TTS (Canopy Labs Orpheus) ---
GROQ_TTS_URL = "https://api.groq.com/openai/v1/audio/speech"


class GroqTTSService:
    """
    Groq text-to-speech (OpenAI-compatible audio/speech endpoint). The model follows the text:
    Arabic script -> the Saudi Arabic model, anything else -> the English model, so callers don't
    need to pass a language. voice_id "default" uses the configured default voice of that model.
    The org admin must accept each model's terms once in the Groq console.
    """

    def __init__(self, api_key: str = None):
        from app.core.config import settings
        self.settings = settings
        self.api_key = api_key or settings.GROQ_API_KEY
        self.last_error = None  # why the last request returned no audio (shown to admins)

    @staticmethod
    def is_arabic(text: str) -> bool:
        return any("\u0600" <= ch <= "\u06ff" or "\u0750" <= ch <= "\u077f" for ch in text or "")

    @staticmethod
    def _retry_after(headers, body: str) -> float:
        """Seconds to wait from the retry-after header, else the message ("try again in 6.2s" / "1m2s")."""
        import re
        try:
            return max(float(headers.get("retry-after", "")), 0.5)
        except ValueError:
            pass
        m = re.search(r"try again in (?:(\d+)m)?([\d.]+)s", body or "")
        return (int(m.group(1) or 0) * 60 + float(m.group(2))) + 0.5 if m else 6.0

    def model_and_voice(self, text: str, voice_id: str) -> tuple[str, str]:
        s = self.settings
        if self.is_arabic(text):
            model, default_voice = s.GROQ_TTS_MODEL_AR, s.GROQ_TTS_VOICE_AR
        else:
            model, default_voice = s.GROQ_TTS_MODEL_EN, s.GROQ_TTS_VOICE_EN
        english_voices = {"troy", "austin", "daniel", "autumn", "diana", "hannah"}
        if not voice_id or voice_id == "default" or (self.is_arabic(text) and voice_id in english_voices):
            return model, default_voice  # an English voice can't speak with the Arabic model
        return model, voice_id

    async def text_to_speech_stream(self, text: str, voice_id: str, session: aiohttp.ClientSession) -> AsyncGenerator[bytes, None]:
        self.last_error = None
        if not self.api_key:
            self.last_error = "no Groq API key (GROQ_API_KEY or a 'groq' credential)"
            logger.error(f"Groq TTS: {self.last_error}")
            return
        model, voice = self.model_and_voice(text, voice_id)
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        data = {"model": model, "voice": voice, "input": text, "response_format": "wav"}
        waited = 0.0
        try:
            while True:
                async with session.post(GROQ_TTS_URL, json=data, headers=headers) as response:
                    if response.status == 429:
                        # requests-per-minute limit (10/min on the on_demand tier): wait as told, then retry
                        delay = self._retry_after(response.headers, await response.text())
                        if waited + delay <= self.settings.GROQ_TTS_MAX_RETRY_WAIT:
                            logger.warning(f"Groq TTS rate limited; retrying in {delay:.1f}s")
                            waited += delay
                            await asyncio.sleep(delay)
                            continue
                        self.last_error = f"{model}: rate limit (requests per minute) — waited {waited:.0f}s"
                        logger.error(f"Groq TTS failed: {self.last_error}")
                        return
                    if response.status != 200:
                    # e.g. model_terms_required, unknown voice (the message lists the valid ones)
                        body = (await response.text())[:500]
                        try:
                            import json
                            body = json.loads(body)["error"]["message"]
                        except Exception:
                            pass
                        self.last_error = f"{model} / {voice}: {body}"
                        logger.error(f"Groq TTS failed ({response.status}): {self.last_error}")
                        return
                    async for chunk in response.content.iter_any():
                        yield chunk
                    return
        except Exception as e:
            self.last_error = str(e)
            logger.exception(e)


# --- Main TTS Router Service ---
class TTSService:
    def __init__(self, openai_api_key: str = None, groq_api_key: str = None):
        self.session = None
        self.voice_engine_service = VoiceEngineTTSService()
        self.localai_service = LocalAITTSService()
        self.openai_service = OpenAITTSService(api_key=openai_api_key)
        self.groq_service = GroqTTSService(api_key=groq_api_key)

    async def _get_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    async def text_to_speech_stream(self, text: str, voice_id: str, provider: str) -> AsyncGenerator[bytes, None]:
        """
        Routes the TTS request to the appropriate provider based on the agent's configuration.

        Supported providers:
        - openai: OpenAI TTS (voices: alloy, echo, fable, onyx, nova, shimmer)
        - localai: Local AI TTS
        - voice_engine: Custom voice engine service
        - groq: Groq TTS (Orpheus English / Saudi Arabic, chosen from the text)
        """
        session = await self._get_session()

        if provider == 'openai':
            async for chunk in self.openai_service.text_to_speech_stream(text, voice_id, session):
                yield chunk
        elif provider == 'localai':
            async for chunk in self.localai_service.text_to_speech_stream(text, voice_id, session):
                yield chunk
        elif provider == 'voice_engine':
            async for chunk in self.voice_engine_service.text_to_speech_stream(text, voice_id, session):
                yield chunk
        elif provider == 'groq':
            async for chunk in self.groq_service.text_to_speech_stream(text, voice_id, session):
                yield chunk
        else:
            async for chunk in self.openai_service.text_to_speech_stream(text, voice_id, session):
                yield chunk

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()
