"""
Handles recording capture, encoding (WAV), upload to MinIO, and DB update.
Both FreeSWITCH (L16 PCM) and Twilio (mulaw) audio are normalised to 16-bit
PCM before being wrapped in a WAV container.
"""
import io
import wave
import audioop
import logging
from typing import Optional

from sqlalchemy.orm import Session

from app.core.object_storage import s3_client, BUCKET_NAME, endpoint_url
from app.models.voice_call import VoiceCall

logger = logging.getLogger(__name__)


def mulaw_to_pcm16(mulaw_bytes: bytes) -> bytes:
    """Convert 8-bit mulaw (8 kHz) to 16-bit linear PCM."""
    return audioop.ulaw2lin(mulaw_bytes, 2)


def _make_wav(pcm_bytes: bytes, sample_rate: int, channels: int = 1) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)          # 16-bit
        w.setframerate(sample_rate)
        w.writeframes(pcm_bytes)
    return buf.getvalue()


def upload_recording(
    db: Session,
    call_sid: str,
    pcm_bytes: bytes,
    sample_rate: int = 8000,
    channels: int = 1,
) -> Optional[str]:
    """
    Encode pcm_bytes as WAV, upload to MinIO, update VoiceCall.recording_url.
    Returns the public URL or None on failure.
    """
    if not pcm_bytes:
        return None

    try:
        wav_bytes = _make_wav(pcm_bytes, sample_rate, channels)
        duration_secs = len(pcm_bytes) / (sample_rate * 2 * channels)

        key = f"recordings/{call_sid}.wav"
        s3_client.put_object(
            Bucket=BUCKET_NAME,
            Key=key,
            Body=wav_bytes,
            ContentType="audio/wav",
        )
        url = f"{endpoint_url}/{BUCKET_NAME}/{key}"
        logger.info(f"[Recording] Uploaded {len(wav_bytes)//1024} KB for call {call_sid} → {url}")

        db_call = db.query(VoiceCall).filter(VoiceCall.call_sid == call_sid).first()
        if db_call:
            db_call.recording_url = url
            db_call.recording_duration_secs = round(duration_secs, 1)
            db.commit()

        return url

    except Exception as e:
        logger.error(f"[Recording] Upload failed for {call_sid}: {e}")
        return None
