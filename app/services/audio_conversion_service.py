"""
Audio conversion service for Twilio Media Streams and FreeSWITCH.

Handles conversion between various audio formats:
- Twilio: mulaw 8kHz
- FreeSWITCH: L16 PCM (8kHz/16kHz/48kHz configurable)
- OpenAI Whisper: 16kHz PCM
- OpenAI TTS: 24kHz PCM
"""
import audioop
import io
import base64
import wave
import logging

logger = logging.getLogger(__name__)


class AudioConversionService:
    """
    Handles audio format conversion between telephony systems (Twilio, FreeSWITCH)
    and OpenAI services (Whisper STT, TTS).
    """

    # Twilio constants
    TWILIO_SAMPLE_RATE = 8000
    TWILIO_CHANNELS = 1
    TWILIO_SAMPLE_WIDTH = 1  # 8-bit mulaw

    # FreeSWITCH constants
    FREESWITCH_DEFAULT_SAMPLE_RATE = 8000
    FREESWITCH_CHANNELS = 1

    # OpenAI constants
    OPENAI_WHISPER_SAMPLE_RATE = 16000
    OPENAI_TTS_SAMPLE_RATE = 24000
    PCM_SAMPLE_WIDTH = 2  # 16-bit PCM

    @staticmethod
    def mulaw_to_pcm(mulaw_bytes: bytes) -> bytes:
        """
        Convert mulaw 8kHz mono to PCM 16-bit.

        Args:
            mulaw_bytes: Raw mulaw audio bytes

        Returns:
            PCM 16-bit audio bytes
        """
        return audioop.ulaw2lin(mulaw_bytes, 2)

    @staticmethod
    def pcm_to_mulaw(pcm_bytes: bytes) -> bytes:
        """
        Convert PCM 16-bit to mulaw 8-bit.

        Args:
            pcm_bytes: Raw PCM 16-bit audio bytes

        Returns:
            Mulaw 8-bit audio bytes
        """
        return audioop.lin2ulaw(pcm_bytes, 2)

    @staticmethod
    def resample(audio_bytes: bytes, from_rate: int, to_rate: int, sample_width: int = 2) -> bytes:
        """
        Resample audio to different sample rate.

        Args:
            audio_bytes: Raw audio bytes
            from_rate: Source sample rate
            to_rate: Target sample rate
            sample_width: Sample width in bytes (default 2 for 16-bit)

        Returns:
            Resampled audio bytes
        """
        if from_rate == to_rate:
            return audio_bytes
        converted, _ = audioop.ratecv(audio_bytes, sample_width, 1, from_rate, to_rate, None)
        return converted

    @staticmethod
    def twilio_to_whisper(mulaw_base64: str) -> bytes:
        """
        Convert Twilio Media Stream audio (mulaw 8kHz base64) to format suitable for Whisper.

        Args:
            mulaw_base64: Base64-encoded mulaw audio from Twilio

        Returns:
            PCM 16-bit 16kHz mono audio bytes suitable for Whisper
        """
        mulaw_bytes = base64.b64decode(mulaw_base64)
        pcm_8k = AudioConversionService.mulaw_to_pcm(mulaw_bytes)
        pcm_16k = AudioConversionService.resample(pcm_8k, 8000, 16000)
        return pcm_16k

    @staticmethod
    def tts_to_twilio(tts_audio: bytes, tts_sample_rate: int = 24000) -> str:
        """
        Convert TTS output (typically 24kHz PCM) to Twilio format (mulaw 8kHz).

        Args:
            tts_audio: Raw PCM audio bytes from TTS
            tts_sample_rate: Sample rate of input audio (default 24000 for OpenAI TTS)

        Returns:
            Base64-encoded mulaw audio for Twilio Media Streams
        """
        # First resample from TTS rate to 8kHz
        pcm_8k = AudioConversionService.resample(tts_audio, tts_sample_rate, 8000)
        # Convert to mulaw
        mulaw_bytes = AudioConversionService.pcm_to_mulaw(pcm_8k)
        return base64.b64encode(mulaw_bytes).decode('utf-8')

    @staticmethod
    def create_wav_buffer(pcm_bytes: bytes, sample_rate: int = 16000) -> io.BytesIO:
        """
        Create a WAV file buffer from PCM bytes for Whisper API.

        Args:
            pcm_bytes: Raw PCM 16-bit audio bytes
            sample_rate: Sample rate of the audio

        Returns:
            BytesIO buffer containing WAV data
        """
        buffer = io.BytesIO()
        with wave.open(buffer, 'wb') as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)  # 16-bit
            wav.setframerate(sample_rate)
            wav.writeframes(pcm_bytes)
        buffer.seek(0)
        return buffer

    @staticmethod
    def process_twilio_audio_chunk(payload: str, audio_buffer: bytearray) -> bytearray:
        """
        Process an incoming Twilio audio chunk and add to buffer.

        Args:
            payload: Base64-encoded mulaw audio from Twilio
            audio_buffer: Existing audio buffer to append to

        Returns:
            Updated audio buffer
        """
        try:
            audio_bytes = base64.b64decode(payload)
            audio_buffer.extend(audio_bytes)
        except Exception as e:
            logger.error(f"Error processing audio chunk: {e}")
        return audio_buffer

    @staticmethod
    def buffer_to_whisper_format(audio_buffer: bytearray) -> bytes:
        """
        Convert accumulated mulaw audio buffer to Whisper-ready PCM.

        Args:
            audio_buffer: Accumulated mulaw audio bytes

        Returns:
            PCM 16-bit 16kHz audio bytes
        """
        # Convert mulaw to PCM
        pcm_8k = AudioConversionService.mulaw_to_pcm(bytes(audio_buffer))
        # Resample to 16kHz for Whisper
        pcm_16k = AudioConversionService.resample(pcm_8k, 8000, 16000)
        return pcm_16k

    @staticmethod
    def chunk_audio_for_streaming(audio_base64: str, chunk_size: int = 8000) -> list:
        """
        Split base64 audio into chunks for streaming to Twilio.

        Args:
            audio_base64: Full base64-encoded audio
            chunk_size: Size of each chunk in characters

        Returns:
            List of audio chunks
        """
        chunks = []
        for i in range(0, len(audio_base64), chunk_size):
            chunks.append(audio_base64[i:i + chunk_size])
        return chunks

    # ==================== FreeSWITCH Methods ====================

    @staticmethod
    def freeswitch_to_whisper(l16_base64: str, sample_rate: int = 8000) -> bytes:
        """
        Convert FreeSWITCH L16 audio to format suitable for Whisper.

        FreeSWITCH mod_audio_stream sends L16 (16-bit signed PCM, little-endian).

        Args:
            l16_base64: Base64-encoded L16 PCM audio from FreeSWITCH
            sample_rate: Sample rate of input audio (default 8000)

        Returns:
            PCM 16-bit 16kHz mono audio bytes suitable for Whisper
        """
        pcm_bytes = base64.b64decode(l16_base64)
        # Resample to 16kHz if needed
        if sample_rate != 16000:
            pcm_bytes = AudioConversionService.resample(pcm_bytes, sample_rate, 16000)
        return pcm_bytes

    @staticmethod
    def tts_to_freeswitch(tts_audio: bytes, tts_sample_rate: int = 24000, target_sample_rate: int = 8000) -> str:
        """
        Convert TTS output to FreeSWITCH L16 format.

        Args:
            tts_audio: Raw PCM audio bytes from TTS
            tts_sample_rate: Sample rate of input audio (default 24000 for OpenAI TTS)
            target_sample_rate: Target sample rate for FreeSWITCH (default 8000)

        Returns:
            Base64-encoded L16 PCM audio for FreeSWITCH
        """
        # Resample from TTS rate to target rate
        pcm_resampled = AudioConversionService.resample(tts_audio, tts_sample_rate, target_sample_rate)
        return base64.b64encode(pcm_resampled).decode('utf-8')

    @staticmethod
    def process_freeswitch_audio_chunk(payload: str, audio_buffer: bytearray) -> bytearray:
        """
        Process an incoming FreeSWITCH audio chunk and add to buffer.

        Args:
            payload: Base64-encoded L16 PCM audio from FreeSWITCH
            audio_buffer: Existing audio buffer to append to

        Returns:
            Updated audio buffer
        """
        try:
            audio_bytes = base64.b64decode(payload)
            audio_buffer.extend(audio_bytes)
        except Exception as e:
            logger.error(f"Error processing FreeSWITCH audio chunk: {e}")
        return audio_buffer

    @staticmethod
    def freeswitch_buffer_to_whisper_format(audio_buffer: bytearray, sample_rate: int = 8000) -> bytes:
        """
        Convert accumulated FreeSWITCH L16 audio buffer to Whisper-ready PCM.

        Args:
            audio_buffer: Accumulated L16 PCM audio bytes
            sample_rate: Sample rate of the buffered audio

        Returns:
            PCM 16-bit 16kHz audio bytes
        """
        pcm_bytes = bytes(audio_buffer)
        # Resample to 16kHz for Whisper if needed
        if sample_rate != 16000:
            pcm_bytes = AudioConversionService.resample(pcm_bytes, sample_rate, 16000)
        return pcm_bytes

    @staticmethod
    def chunk_audio_for_freeswitch(audio_base64: str, chunk_size: int = 640) -> list:
        """
        Split base64 audio into chunks for streaming to FreeSWITCH.

        Default chunk size is 640 bytes (20ms at 8kHz, 16-bit).

        Args:
            audio_base64: Full base64-encoded audio
            chunk_size: Size of each chunk in bytes (before base64)

        Returns:
            List of base64-encoded audio chunks
        """
        audio_bytes = base64.b64decode(audio_base64)
        chunks = []
        for i in range(0, len(audio_bytes), chunk_size):
            chunk = audio_bytes[i:i + chunk_size]
            chunks.append(base64.b64encode(chunk).decode('utf-8'))
        return chunks
