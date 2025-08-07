import aiohttp
import os
from typing import AsyncGenerator

LOCALAI_TTS_URL = os.getenv("LOCALAI_TTS_URL", "http://localhost:8082/tts")

class LocalAITTSService:
    def __init__(self):
        self.session = None

    async def _get_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    async def text_to_speech_stream(self, text: str, voice_id: str) -> AsyncGenerator[bytes, None]:
        """
        Streams audio from a local AI TTS provider.
        """
        session = await self._get_session()
        
        headers = { "Content-Type": "application/json" }
        data = {
            "model": "voice-en-us-ryan-medium", # Or voice-en-us-amy-low
            "input": text,
            # "voice": voice_id, # Assumes local AI uses a voice name
        }

        try:
            async with session.post(LOCALAI_TTS_URL, json=data, headers=headers) as response:
                response.raise_for_status()
                async for chunk in response.content.iter_any():
                    yield chunk
        except Exception as e:
            print(f"Error during Local AI TTS streaming: {e}")
            
    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()
