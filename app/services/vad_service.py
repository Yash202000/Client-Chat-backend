"""
Voice Activity Detection (VAD) service using Silero VAD.

Provides streaming VAD for real-time speech detection in voice calls.
Supports both Twilio (mulaw 8kHz) and FreeSWITCH (L16 PCM) audio formats.
"""
import torch
import numpy as np
import audioop
import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class VADEvent(Enum):
    """VAD event types."""
    SPEECH_START = "speech_start"
    SPEECH_END = "speech_end"
    SPEECH_CONTINUE = "speech_continue"
    SILENCE = "silence"


@dataclass
class VADResult:
    """Result from VAD processing."""
    event: VADEvent
    probability: float
    speech_duration_ms: float = 0
    silence_duration_ms: float = 0


class SileroVADService:
    """
    Silero VAD service for streaming voice activity detection.

    Uses the Silero VAD model for accurate speech detection with configurable
    thresholds and timing parameters.
    """

    # Singleton model instance (loaded once, shared across all instances)
    _model = None
    _model_sample_rate = 16000  # Silero VAD works best at 16kHz

    def __init__(
        self,
        threshold: float = 0.5,
        neg_threshold: Optional[float] = None,
        min_speech_duration_ms: int = 50,  # LiveKit default: 0.05s
        min_silence_duration_ms: int = 550,  # LiveKit default: 0.55s
        speech_pad_ms: int = 30,
        sample_rate: int = 8000,  # Input sample rate (Twilio/FreeSWITCH default)
    ):
        """
        Initialize the VAD service.

        Args:
            threshold: Speech probability threshold (0-1). Default 0.5 (LiveKit default).
            neg_threshold: Threshold to end speech. Default threshold - 0.15 (LiveKit default).
            min_speech_duration_ms: Minimum speech duration to trigger start event. Default 50ms (LiveKit: 0.05s).
            min_silence_duration_ms: Minimum silence duration to trigger end event. Default 550ms (LiveKit: 0.55s).
            speech_pad_ms: Padding added to speech boundaries.
            sample_rate: Input audio sample rate (8000 or 16000).
        """
        self.threshold = threshold
        self.neg_threshold = neg_threshold if neg_threshold is not None else max(threshold - 0.15, 0.01)
        self.min_speech_duration_ms = min_speech_duration_ms
        self.min_silence_duration_ms = min_silence_duration_ms
        self.speech_pad_ms = speech_pad_ms
        self.input_sample_rate = sample_rate

        # State tracking
        self.is_speaking = False
        self.speech_start_samples = 0
        self.silence_start_samples = 0
        self.current_sample = 0
        self.triggered = False

        # Audio buffer for resampling (accumulate samples for model)
        self.audio_buffer = np.array([], dtype=np.float32)

        # Model window size (Silero expects specific chunk sizes)
        # 512 samples at 16kHz = 32ms
        self.window_size = 512

        # Load model if not already loaded
        self._ensure_model_loaded()

        # Reset model state for this instance
        self._reset_model_state()

        logger.info(
            f"SileroVAD initialized: threshold={threshold}, neg_threshold={self.neg_threshold}, "
            f"min_speech={min_speech_duration_ms}ms, min_silence={min_silence_duration_ms}ms, "
            f"sample_rate={sample_rate}"
        )

    @classmethod
    def _ensure_model_loaded(cls):
        """Load the Silero VAD model (singleton)."""
        if cls._model is None:
            logger.info("Loading Silero VAD model...")
            cls._model, _ = torch.hub.load(
                repo_or_dir='snakers4/silero-vad',
                model='silero_vad',
                force_reload=False,
                onnx=False,
                trust_repo=True
            )
            cls._model.eval()
            logger.info("Silero VAD model loaded successfully")

    def _reset_model_state(self):
        """Reset the model's internal state."""
        if self._model is not None:
            self._model.reset_states()

    def reset(self):
        """Reset VAD state for a new conversation."""
        self.is_speaking = False
        self.speech_start_samples = 0
        self.silence_start_samples = 0
        self.current_sample = 0
        self.triggered = False
        self.audio_buffer = np.array([], dtype=np.float32)
        self._reset_model_state()
        logger.debug("VAD state reset")

    def _resample_to_16k(self, audio_8k: bytes) -> bytes:
        """Resample 8kHz PCM to 16kHz."""
        if self.input_sample_rate == 16000:
            return audio_8k
        resampled, _ = audioop.ratecv(audio_8k, 2, 1, self.input_sample_rate, 16000, None)
        return resampled

    def _mulaw_to_pcm(self, mulaw_bytes: bytes) -> bytes:
        """Convert mulaw to 16-bit PCM."""
        return audioop.ulaw2lin(mulaw_bytes, 2)

    def _bytes_to_float32(self, pcm_bytes: bytes) -> np.ndarray:
        """Convert PCM bytes to float32 numpy array normalized to [-1, 1]."""
        # Convert bytes to int16
        audio_int16 = np.frombuffer(pcm_bytes, dtype=np.int16)
        # Normalize to float32 [-1, 1]
        audio_float32 = audio_int16.astype(np.float32) / 32768.0
        return audio_float32

    def _samples_to_ms(self, samples: int) -> float:
        """Convert samples to milliseconds at model sample rate."""
        return (samples / self._model_sample_rate) * 1000

    def process_mulaw(self, mulaw_bytes: bytes) -> Optional[VADResult]:
        """
        Process mulaw audio (Twilio format) through VAD.

        Args:
            mulaw_bytes: Raw mulaw 8kHz audio bytes

        Returns:
            VADResult with event type and metadata, or None if no event
        """
        # Convert mulaw to PCM
        pcm_8k = self._mulaw_to_pcm(mulaw_bytes)
        return self.process_pcm(pcm_8k)

    def process_l16(self, l16_bytes: bytes) -> Optional[VADResult]:
        """
        Process L16 PCM audio (FreeSWITCH format) through VAD.

        Args:
            l16_bytes: Raw L16 PCM audio bytes (already 16-bit)

        Returns:
            VADResult with event type and metadata, or None if no event
        """
        return self.process_pcm(l16_bytes)

    def process_pcm(self, pcm_bytes: bytes) -> Optional[VADResult]:
        """
        Process PCM audio through VAD.

        Args:
            pcm_bytes: Raw 16-bit PCM audio bytes

        Returns:
            VADResult with event type and metadata, or None if no event
        """
        # Resample to 16kHz if needed
        pcm_16k = self._resample_to_16k(pcm_bytes)

        # Convert to float32
        audio_float = self._bytes_to_float32(pcm_16k)

        # Add to buffer
        self.audio_buffer = np.concatenate([self.audio_buffer, audio_float])

        # Process in chunks of window_size
        result = None
        while len(self.audio_buffer) >= self.window_size:
            chunk = self.audio_buffer[:self.window_size]
            self.audio_buffer = self.audio_buffer[self.window_size:]

            # Run inference
            chunk_result = self._process_chunk(chunk)
            if chunk_result is not None:
                result = chunk_result  # Return the latest event

        return result

    def _process_chunk(self, audio_chunk: np.ndarray) -> Optional[VADResult]:
        """
        Process a single audio chunk through the model.

        Args:
            audio_chunk: Float32 audio chunk of window_size samples

        Returns:
            VADResult if state changed, None otherwise
        """
        # Convert to tensor
        audio_tensor = torch.from_numpy(audio_chunk)

        # Run model inference
        with torch.no_grad():
            speech_prob = self._model(audio_tensor, self._model_sample_rate).item()

        # Update sample counter
        self.current_sample += len(audio_chunk)

        # Determine speech state using hysteresis
        is_speech = False
        if self.is_speaking:
            # Currently speaking - need to drop below neg_threshold to stop
            is_speech = speech_prob >= self.neg_threshold
        else:
            # Currently silent - need to exceed threshold to start
            is_speech = speech_prob >= self.threshold

        result = None

        if is_speech:
            if not self.is_speaking:
                # Potential speech start
                if not self.triggered:
                    self.speech_start_samples = self.current_sample
                    self.triggered = True

                # Check if we've accumulated enough speech
                speech_duration_ms = self._samples_to_ms(self.current_sample - self.speech_start_samples)
                if speech_duration_ms >= self.min_speech_duration_ms:
                    self.is_speaking = True
                    self.silence_start_samples = 0
                    result = VADResult(
                        event=VADEvent.SPEECH_START,
                        probability=speech_prob,
                        speech_duration_ms=speech_duration_ms
                    )
                    logger.debug(f"Speech started: prob={speech_prob:.3f}, duration={speech_duration_ms:.0f}ms")
            else:
                # Continuing speech
                self.silence_start_samples = 0
                speech_duration_ms = self._samples_to_ms(self.current_sample - self.speech_start_samples)
                result = VADResult(
                    event=VADEvent.SPEECH_CONTINUE,
                    probability=speech_prob,
                    speech_duration_ms=speech_duration_ms
                )
        else:
            if self.is_speaking:
                # Potential speech end
                if self.silence_start_samples == 0:
                    self.silence_start_samples = self.current_sample

                silence_duration_ms = self._samples_to_ms(self.current_sample - self.silence_start_samples)
                if silence_duration_ms >= self.min_silence_duration_ms:
                    self.is_speaking = False
                    self.triggered = False
                    speech_duration_ms = self._samples_to_ms(self.silence_start_samples - self.speech_start_samples)
                    result = VADResult(
                        event=VADEvent.SPEECH_END,
                        probability=speech_prob,
                        speech_duration_ms=speech_duration_ms,
                        silence_duration_ms=silence_duration_ms
                    )
                    logger.debug(f"Speech ended: prob={speech_prob:.3f}, speech={speech_duration_ms:.0f}ms, silence={silence_duration_ms:.0f}ms")
            else:
                # Continuing silence
                self.triggered = False
                result = VADResult(
                    event=VADEvent.SILENCE,
                    probability=speech_prob
                )

        return result

    def get_state(self) -> Dict[str, Any]:
        """Get current VAD state for debugging."""
        return {
            "is_speaking": self.is_speaking,
            "triggered": self.triggered,
            "current_sample": self.current_sample,
            "speech_start_samples": self.speech_start_samples,
            "silence_start_samples": self.silence_start_samples,
            "buffer_size": len(self.audio_buffer),
        }


# Global VAD instance for prewarming
_global_vad: Optional[SileroVADService] = None


def get_vad_service(
    threshold: float = 0.5,
    min_speech_duration_ms: int = 250,
    min_silence_duration_ms: int = 100,
    sample_rate: int = 8000,
) -> SileroVADService:
    """
    Get a VAD service instance.

    Args:
        threshold: Speech probability threshold
        min_speech_duration_ms: Minimum speech duration
        min_silence_duration_ms: Minimum silence duration
        sample_rate: Input audio sample rate

    Returns:
        Configured SileroVADService instance
    """
    return SileroVADService(
        threshold=threshold,
        min_speech_duration_ms=min_speech_duration_ms,
        min_silence_duration_ms=min_silence_duration_ms,
        sample_rate=sample_rate,
    )


def prewarm_vad():
    """Prewarm the VAD model by loading it ahead of time."""
    global _global_vad
    if _global_vad is None:
        logger.info("Prewarming Silero VAD model...")
        _global_vad = SileroVADService()
        logger.info("Silero VAD model prewarmed")
    return _global_vad
