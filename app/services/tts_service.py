
import aiohttp
from typing import AsyncGenerator
import os

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
            print(f"Error streaming from Voice Engine: {e}")

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
            print(f"Error streaming from Local AI: {e}")

# --- Main TTS Router Service ---
class TTSService:
    def __init__(self):
        self.session = None
        self.voice_engine_service = VoiceEngineTTSService()
        self.localai_service = LocalAITTSService()

    async def _get_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    async def text_to_speech_stream(self, text: str, voice_id: str, provider: str) -> AsyncGenerator[bytes, None]:
        """
        Routes the TTS request to the appropriate provider based on the agent's configuration.
        """
        session = await self._get_session()
        
        if provider == 'localai':
            async for chunk in self.localai_service.text_to_speech_stream(text, voice_id, session):
                yield chunk
        elif provider == 'voice_engine':
            async for chunk in self.voice_engine_service.text_to_speech_stream(text, voice_id, session):
                yield chunk
        else:
            print(f"Unknown TTS provider: {provider}. Defaulting to voice_engine.")
            async for chunk in self.voice_engine_service.text_to_speech_stream(text, voice_id, session):
                yield chunk

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()
