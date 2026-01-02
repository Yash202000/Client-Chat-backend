"""
OpenAI Realtime API Service for ultra-low-latency voice conversations.

This service manages WebSocket connections to OpenAI's Realtime API,
enabling voice-to-voice conversations with ~300ms latency.
"""
import asyncio
import base64
import json
import logging
from typing import AsyncGenerator, Callable, Dict, Any, Optional, List
from dataclasses import dataclass, field
import websockets
from websockets.client import WebSocketClientProtocol

from app.core.config import settings

logger = logging.getLogger(__name__)

# OpenAI Realtime API endpoint
OPENAI_REALTIME_URL = "wss://api.openai.com/v1/realtime"


@dataclass
class RealtimeEvent:
    """Represents an event from the OpenAI Realtime API."""
    type: str
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FunctionCall:
    """Represents a function call from the Realtime API."""
    call_id: str
    name: str
    arguments: str


class OpenAIRealtimeService:
    """
    Manages OpenAI Realtime API WebSocket connection for voice conversations.

    Features:
    - Bidirectional audio streaming
    - Function/tool calling support
    - Automatic session configuration
    - Audio format conversion helpers
    """

    def __init__(
        self,
        model: str = None,
        voice: str = None,
        system_prompt: str = None,
        tools: List[Dict[str, Any]] = None,
    ):
        self.model = model or settings.OPENAI_REALTIME_MODEL
        self.voice = voice or settings.OPENAI_REALTIME_VOICE
        self.system_prompt = system_prompt
        self.tools = tools or []

        self.ws: Optional[WebSocketClientProtocol] = None
        self.session_id: Optional[str] = None
        self.is_connected = False

        # Event queues
        self._audio_queue: asyncio.Queue = asyncio.Queue()
        self._event_queue: asyncio.Queue = asyncio.Queue()
        self._pending_function_calls: Dict[str, FunctionCall] = {}

        # Callbacks
        self._on_audio_callback: Optional[Callable[[bytes], None]] = None
        self._on_transcript_callback: Optional[Callable[[str, str], None]] = None
        self._on_function_call_callback: Optional[Callable[[FunctionCall], None]] = None

    async def connect(self) -> bool:
        """
        Connect to OpenAI Realtime API.

        Returns:
            bool: True if connection successful
        """
        if not settings.OPENAI_API_KEY:
            logger.error("OPENAI_API_KEY not configured")
            return False

        url = f"{OPENAI_REALTIME_URL}?model={self.model}"
        headers = {
            "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
            "OpenAI-Beta": "realtime=v1",
        }

        try:
            self.ws = await websockets.connect(
                url,
                additional_headers=headers,
                ping_interval=20,
                ping_timeout=10,
            )
            self.is_connected = True
            logger.info(f"Connected to OpenAI Realtime API with model {self.model}")

            # Wait for session.created event
            await self._wait_for_session_created()

            # Configure session
            await self._configure_session()

            return True

        except Exception as e:
            logger.error(f"Failed to connect to OpenAI Realtime API: {e}")
            self.is_connected = False
            return False

    async def _wait_for_session_created(self) -> None:
        """Wait for the session.created event from the API."""
        try:
            message = await asyncio.wait_for(self.ws.recv(), timeout=10.0)
            event = json.loads(message)

            if event.get("type") == "session.created":
                self.session_id = event.get("session", {}).get("id")
                logger.info(f"Session created: {self.session_id}")
            else:
                logger.warning(f"Unexpected first event: {event.get('type')}")
        except asyncio.TimeoutError:
            logger.error("Timeout waiting for session.created")
            raise

    async def _configure_session(self) -> None:
        """Configure the session with voice, modalities, and tools."""
        config = {
            "type": "session.update",
            "session": {
                "modalities": ["text", "audio"],
                "voice": self.voice,
                "input_audio_format": "pcm16",
                "output_audio_format": "pcm16",
                "input_audio_transcription": {
                    "model": "whisper-1"
                },
                "turn_detection": {
                    "type": "server_vad",
                    "threshold": 0.5,
                    "prefix_padding_ms": 300,
                    "silence_duration_ms": 500,
                },
            }
        }

        # Add system prompt if provided
        if self.system_prompt:
            config["session"]["instructions"] = self.system_prompt

        # Add tools if provided
        if self.tools:
            config["session"]["tools"] = self.tools
            config["session"]["tool_choice"] = "auto"

        await self._send_event(config)
        logger.info(f"Session configured with voice={self.voice}, tools={len(self.tools)}")

    async def _send_event(self, event: Dict[str, Any]) -> None:
        """Send an event to the Realtime API."""
        if self.ws and self.is_connected:
            await self.ws.send(json.dumps(event))

    async def send_audio(self, audio_bytes: bytes) -> None:
        """
        Send audio to the Realtime API.

        Args:
            audio_bytes: PCM 16-bit, 24kHz, mono audio data
        """
        if not self.is_connected:
            return

        # Base64 encode the audio
        audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")

        event = {
            "type": "input_audio_buffer.append",
            "audio": audio_b64,
        }
        await self._send_event(event)

    async def commit_audio(self) -> None:
        """Commit the audio buffer to trigger processing."""
        if not self.is_connected:
            return

        event = {"type": "input_audio_buffer.commit"}
        await self._send_event(event)

    async def cancel_response(self) -> None:
        """Cancel the current response (for interruption handling)."""
        if not self.is_connected:
            return

        event = {"type": "response.cancel"}
        await self._send_event(event)

    async def submit_function_result(self, call_id: str, result: str) -> None:
        """
        Submit the result of a function call.

        Args:
            call_id: The function call ID
            result: The function result as a string
        """
        if not self.is_connected:
            return

        event = {
            "type": "conversation.item.create",
            "item": {
                "type": "function_call_output",
                "call_id": call_id,
                "output": result,
            }
        }
        await self._send_event(event)

        # Trigger response generation after function result
        await self._send_event({"type": "response.create"})

        logger.info(f"Submitted function result for call_id={call_id}")

    async def receive_events(self) -> AsyncGenerator[RealtimeEvent, None]:
        """
        Receive events from the Realtime API.

        Yields:
            RealtimeEvent objects for each event received
        """
        if not self.ws or not self.is_connected:
            return

        try:
            async for message in self.ws:
                try:
                    event_data = json.loads(message)
                    event_type = event_data.get("type", "unknown")

                    # Create event object
                    event = RealtimeEvent(type=event_type, data=event_data)

                    # Log non-audio events for debugging
                    if event_type not in ("response.audio.delta", "input_audio_buffer.speech_started"):
                        logger.debug(f"Realtime event: {event_type}")

                    yield event

                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse Realtime event: {e}")
                    continue

        except websockets.exceptions.ConnectionClosed as e:
            logger.info(f"Realtime WebSocket closed: {e}")
            self.is_connected = False
        except Exception as e:
            logger.error(f"Error receiving Realtime events: {e}")
            self.is_connected = False

    def extract_audio_delta(self, event: RealtimeEvent) -> Optional[bytes]:
        """
        Extract audio bytes from a response.audio.delta event.

        Args:
            event: The RealtimeEvent

        Returns:
            PCM 16-bit, 24kHz audio bytes or None
        """
        if event.type != "response.audio.delta":
            return None

        audio_b64 = event.data.get("delta")
        if audio_b64:
            return base64.b64decode(audio_b64)
        return None

    def extract_function_call(self, event: RealtimeEvent) -> Optional[FunctionCall]:
        """
        Extract function call from a response.function_call_arguments.done event.

        Args:
            event: The RealtimeEvent

        Returns:
            FunctionCall object or None
        """
        if event.type != "response.output_item.done":
            return None

        item = event.data.get("item", {})
        if item.get("type") != "function_call":
            return None

        return FunctionCall(
            call_id=item.get("call_id", ""),
            name=item.get("name", ""),
            arguments=item.get("arguments", "{}"),
        )

    def extract_transcript(self, event: RealtimeEvent) -> Optional[tuple]:
        """
        Extract transcript from transcription events.

        Args:
            event: The RealtimeEvent

        Returns:
            Tuple of (role, text) or None
        """
        if event.type == "conversation.item.input_audio_transcription.completed":
            return ("user", event.data.get("transcript", ""))
        elif event.type == "response.audio_transcript.done":
            return ("assistant", event.data.get("transcript", ""))
        return None

    async def disconnect(self) -> None:
        """Disconnect from the Realtime API."""
        self.is_connected = False
        if self.ws:
            try:
                await self.ws.close()
            except Exception as e:
                logger.error(f"Error closing Realtime WebSocket: {e}")
            self.ws = None
        logger.info("Disconnected from OpenAI Realtime API")


# Audio format conversion utilities

def convert_mulaw_8k_to_pcm_24k(mulaw_bytes: bytes) -> bytes:
    """
    Convert Twilio mulaw 8kHz audio to PCM 16-bit 24kHz for OpenAI Realtime.

    Args:
        mulaw_bytes: mulaw encoded 8kHz audio

    Returns:
        PCM 16-bit 24kHz mono audio
    """
    import audioop

    # Decode mulaw to PCM 16-bit
    pcm_8k = audioop.ulaw2lin(mulaw_bytes, 2)

    # Resample from 8kHz to 24kHz (3x)
    pcm_24k, _ = audioop.ratecv(pcm_8k, 2, 1, 8000, 24000, None)

    return pcm_24k


def convert_pcm_24k_to_mulaw_8k(pcm_24k_bytes: bytes) -> bytes:
    """
    Convert OpenAI Realtime PCM 24kHz audio to Twilio mulaw 8kHz.

    Args:
        pcm_24k_bytes: PCM 16-bit 24kHz mono audio

    Returns:
        mulaw encoded 8kHz audio
    """
    import audioop

    # Resample from 24kHz to 8kHz (1/3)
    pcm_8k, _ = audioop.ratecv(pcm_24k_bytes, 2, 1, 24000, 8000, None)

    # Encode to mulaw
    mulaw = audioop.lin2ulaw(pcm_8k, 2)

    return mulaw


def convert_l16_8k_to_pcm_24k(l16_bytes: bytes) -> bytes:
    """
    Convert FreeSWITCH L16 8kHz audio to PCM 16-bit 24kHz for OpenAI Realtime.

    Args:
        l16_bytes: L16 (PCM 16-bit) 8kHz audio

    Returns:
        PCM 16-bit 24kHz mono audio
    """
    import audioop

    # Resample from 8kHz to 24kHz (3x)
    pcm_24k, _ = audioop.ratecv(l16_bytes, 2, 1, 8000, 24000, None)

    return pcm_24k


def convert_pcm_24k_to_l16_8k(pcm_24k_bytes: bytes) -> bytes:
    """
    Convert OpenAI Realtime PCM 24kHz audio to FreeSWITCH L16 8kHz.

    Args:
        pcm_24k_bytes: PCM 16-bit 24kHz mono audio

    Returns:
        L16 (PCM 16-bit) 8kHz audio
    """
    import audioop

    # Resample from 24kHz to 8kHz (1/3)
    l16_8k, _ = audioop.ratecv(pcm_24k_bytes, 2, 1, 24000, 8000, None)

    return l16_8k
