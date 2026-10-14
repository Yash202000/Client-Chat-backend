"""
LiveKit text-to-speech backed by the shared TTSService (app/services/tts_service.py), so phone calls
speak with the Agent's own TTS provider + voice (openai / localai / voice_engine) like every other
channel, instead of a provider fixed in the voice process.
"""
import uuid

from livekit.agents import APIConnectionError, APIConnectOptions, tts
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS

SAMPLE_RATE = 24000
NUM_CHANNELS = 1


class ProviderTTS(tts.TTS):
    def __init__(self, provider: str, voice: str, keys: dict):
        super().__init__(capabilities=tts.TTSCapabilities(streaming=False), sample_rate=SAMPLE_RATE,
                         num_channels=NUM_CHANNELS)
        from app.services.tts_service import TTSService

        self._provider, self._voice = provider, voice
        self._service = TTSService(openai_api_key=keys.get("openai"), groq_api_key=keys.get("groq"))

    @property
    def model(self) -> str:
        return self._voice

    @property
    def provider(self) -> str:
        return self._provider

    def synthesize(self, text: str, *, conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS) -> "ChunkedStream":
        return ChunkedStream(tts=self, input_text=text, conn_options=conn_options)

    async def aclose(self) -> None:
        await self._service.close()


class ChunkedStream(tts.ChunkedStream):
    def __init__(self, *, tts: ProviderTTS, input_text: str, conn_options: APIConnectOptions) -> None:
        super().__init__(tts=tts, input_text=input_text, conn_options=conn_options)
        self._provider_tts = tts

    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        from app.services.tts_prompt_service import sniff_audio

        t = self._provider_tts
        started = False
        try:
            async for chunk in t._service.text_to_speech_stream(self.input_text, t._voice, t._provider):
                if not chunk:
                    continue
                if not started:  # providers return mp3 / wav / ogg: tell the decoder which
                    output_emitter.initialize(request_id=uuid.uuid4().hex, sample_rate=SAMPLE_RATE,
                                              num_channels=NUM_CHANNELS, mime_type=sniff_audio(chunk)[0])
                    started = True
                output_emitter.push(chunk)
        except Exception as e:
            raise APIConnectionError(f"{t.provider} text-to-speech failed: {e}") from e
        if not started:  # TTSService logs and swallows provider errors
            reason = t._service.groq_service.last_error if t._provider == "groq" else None
            raise APIConnectionError(f"{t.provider} text-to-speech returned no audio: {reason or 'provider down?'}")
        output_emitter.flush()
