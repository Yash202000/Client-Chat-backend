from fastapi import WebSocket, UploadFile
import aiohttp
import os
import asyncio
from typing import Literal

# Deepgram configuration
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")
DEEPGRAM_URL = "https://api.deepgram.com/v1/listen?model=nova-2&interim_results=true&endpointing=200"

# Groq configuration
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_API_URL = "https://api.groq.com/openai/v1/audio"

class GroqSTTService:
    def __init__(self, api_key: str = None):
        self.api_key = api_key or GROQ_API_KEY
        self.base_url = GROQ_API_URL

        # Validate API key is present
        if not self.api_key:
            raise ValueError(
                "Groq API key is missing. Please set GROQ_API_KEY environment variable "
                "or provide api_key parameter, or configure agent's Groq credential in vault."
            )

    async def transcribe(self, file: UploadFile, model: Literal["whisper-large-v3-turbo", "whisper-large-v3"] = "whisper-large-v3-turbo") -> dict:
        """
        Convert audio to text using Groq's transcription service.
        """
        url = f"{self.base_url}/transcriptions"
        return await self._request(url, file, model)

    async def translate(self, file: UploadFile, model: Literal["whisper-large-v3-turbo", "whisper-large-v3"] = "whisper-large-v3-turbo") -> dict:
        """
        Translate audio to English text using Groq's translation service.
        """
        url = f"{self.base_url}/translations"
        return await self._request(url, file, model)

    async def _request(self, url: str, file: UploadFile, model: str) -> dict:
        async with aiohttp.ClientSession() as session:
            form = aiohttp.FormData()
            form.add_field("file", await file.read(), filename=file.filename, content_type=file.content_type)
            form.add_field("model", model)
            
            headers = {"Authorization": f"Bearer {self.api_key}"}
            
            async with session.post(url, data=form, headers=headers) as response:
                response.raise_for_status()
                return await response.json()

class STTService:
    def __init__(self, websocket: WebSocket):
        self.websocket = websocket
        self.session = aiohttp.ClientSession()
        self.deepgram_ws = None

    async def connect(self):
        try:
            self.deepgram_ws = await self.session.ws_connect(
                DEEPGRAM_URL,
                headers={"Authorization": f"Token {DEEPGRAM_API_KEY}"}
            )
            return True
        except Exception as e:
            print(f"Error connecting to Deepgram: {e}")
            return False

    async def stream(self):
        """
        Streams audio from the client to Deepgram and sends back transcripts.
        """
        if not self.deepgram_ws:
            await self.connect()

        async def deepgram_receiver():
            """Receives transcripts from Deepgram and forwards them to the client."""
            while self.deepgram_ws and not self.deepgram_ws.closed:
                try:
                    message = await self.deepgram_ws.receive_json()
                    if message.get("type") == "Results":
                        transcript = message["channel"]["alternatives"][0]["transcript"]
                        if transcript:
                            # Forward the transcript back to the client
                            await self.websocket.send_json({
                                "type": "transcript",
                                "data": transcript
                            })
                except Exception as e:
                    print(f"Error receiving from Deepgram: {e}")
                    break

        async def client_receiver():
            """Receives audio from the client and forwards it to Deepgram."""
            try:
                while True:
                    audio_chunk = await self.websocket.receive_bytes()
                    if self.deepgram_ws and not self.deepgram_ws.closed:
                        await self.deepgram_ws.send_bytes(audio_chunk)
                    else:
                        print("Deepgram connection not available.")
                        break
            except Exception as e:
                print(f"Error receiving from client: {e}")

        # Run both tasks concurrently
        if self.deepgram_ws:
            await asyncio.gather(deepgram_receiver(), client_receiver())

    async def close(self):
        if self.deepgram_ws and not self.deepgram_ws.closed:
            await self.deepgram_ws.close()
        if self.session and not self.session.closed:
            await self.session.close()