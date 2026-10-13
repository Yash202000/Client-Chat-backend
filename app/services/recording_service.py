"""
Call recording for contact-centre calls (FR-CC-050/052, NFR-008): LiveKit Egress mixes the room's
audio and uploads an OGG file to MinIO / S3. Playback and download are separate permissions and
every access is logged (RPT-10).

Pause (FR-CC-051): pausing stops the egress; resuming starts a new one, so a paused call is stored as
ordered parts (`recording_parts`) and the paused stretch is never recorded. Pauses are audited, and a
transfer resumes the recording so the next agent's part is recorded.
"""
import logging
from datetime import datetime
from typing import Optional

from livekit import api
from livekit.protocol import egress as egress_proto
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.voice_call import VoiceCall
from app.services import call_service

logger = logging.getLogger(__name__)


def _s3() -> api.S3Upload:
    scheme = "https" if settings.minio_secure else "http"
    return api.S3Upload(
        access_key=settings.minio_access_key, secret=settings.minio_secret_key, region="us-east-1",
        endpoint=f"{scheme}://{settings.minio_endpoint}", bucket=settings.minio_bucket, force_path_style=True,
    )


def object_key(call: VoiceCall, part: int = 1) -> str:
    day = (call.started_at or datetime.utcnow()).strftime("%Y/%m/%d")
    suffix = "" if part == 1 else f"-part{part}"
    return f"call-recordings/{call.company_id}/{day}/call-{call.id}{suffix}.ogg"


class RecordingError(Exception):
    pass


async def _start_egress(call: VoiceCall, key: str) -> str:
    from app.services.livekit_sip_service import _api
    lk = _api()
    try:
        info = await lk.egress.start_room_composite_egress(api.RoomCompositeEgressRequest(
            room_name=call.room_name, audio_only=True,
            file_outputs=[api.EncodedFileOutput(file_type=egress_proto.EncodedFileType.OGG, filepath=key, s3=_s3(),
                                             disable_manifest=True)],
        ))
        return info.egress_id
    finally:
        await lk.aclose()


def _add_part(call: VoiceCall, egress_id: str, key: str) -> None:
    call.recording_parts = list(call.recording_parts or []) + [
        {"egress_id": egress_id, "key": key, "started_at": datetime.utcnow().isoformat() + "Z", "status": "recording"}]


def _update_part(call: VoiceCall, egress_id: str, **fields) -> None:
    call.recording_parts = [dict(p, **fields) if p.get("egress_id") == egress_id else p for p in (call.recording_parts or [])]


def start_in_background(call_id: int) -> None:
    """Webhooks must stay fast: start the egress without blocking the caller of this function."""
    import asyncio

    async def run():
        from app.core.database import SessionLocal
        db = SessionLocal()
        try:
            call = db.query(VoiceCall).filter(VoiceCall.id == call_id).first()
            if call:
                await start(db, call)
        except Exception:
            logger.exception(f"[recording] start failed for call {call_id}")
        finally:
            db.close()
    asyncio.create_task(run())


async def start(db: Session, call: VoiceCall) -> Optional[str]:
    """Start recording once the call is answered (once per call; no-op if recording is off for the number)."""
    if call.recording_egress_id or call.recording_status or not call.room_name:
        return call.recording_egress_id
    # claim the attempt first so concurrent webhooks don't start two recordings
    claimed = db.query(VoiceCall).filter(VoiceCall.id == call.id, VoiceCall.recording_status.is_(None)) \
        .update({"recording_status": "starting"}, synchronize_session=False)
    db.commit()
    if not claimed:
        return None
    db.refresh(call)
    if call.phone_number and not call.phone_number.recording_enabled:
        call.recording_status = "off"
        db.commit()
        return None
    key = object_key(call)
    try:
        egress_id = await _start_egress(call, key)
    except Exception as e:
        logger.warning(f"[recording] could not start for call {call.id}: {e}")
        call.recording_status = "failed"
        db.commit()
        call_service.record_event(db, call, "recording_failed", payload={"error": str(e)[:300]})
        return None
    call.recording_egress_id = egress_id
    call.recording_status = "recording"
    call.recording_started_at = datetime.utcnow()
    call.recording_object_key = key
    _add_part(call, egress_id, key)
    db.commit()
    call_service.record_event(db, call, "recording_started", payload={"egress_id": egress_id})
    return egress_id


async def pause(db: Session, call: VoiceCall, user_id: int, reason: str = "") -> dict:
    """Stop recording until resumed (e.g. while the caller gives card details). Audited."""
    from app.core.audit import log_action

    if call.status not in call_service.ACTIVE_STATUSES:
        raise RecordingError("The call has ended")
    if call.recording_status != "recording" or not call.recording_egress_id:
        raise RecordingError(f"The call is not being recorded ({call.recording_status or 'not recorded'})")
    from app.services.livekit_sip_service import _api
    lk = _api()
    try:
        await lk.egress.stop_egress(api.StopEgressRequest(egress_id=call.recording_egress_id))
    except api.TwirpError as e:
        raise RecordingError(f"Could not pause the recording: {e.message}")
    finally:
        await lk.aclose()
    call.recording_status = "paused"
    call.recording_paused_at = datetime.utcnow()
    _update_part(call, call.recording_egress_id, ended_at=call.recording_paused_at.isoformat() + "Z", status="stopping")
    db.commit()
    call_service.record_event(db, call, "recording_paused", actor_type="agent", actor_user_id=user_id,
                              payload={"reason": reason or None})
    log_action(db, call.company_id, user_id, "recording.paused", entity_type="voice_call", entity_id=call.id,
               changes={"reason": reason or None})
    db.commit()
    return {"recording_status": call.recording_status}


async def resume(db: Session, call: VoiceCall, user_id: Optional[int], reason: str = "") -> dict:
    """Start a new recording part. user_id None = automatic (transfer)."""
    from app.core.audit import log_action

    if call.recording_status != "paused":
        raise RecordingError("The recording is not paused")
    if call.status not in call_service.ACTIVE_STATUSES:
        raise RecordingError("The call has ended")
    key = object_key(call, part=len(call.recording_parts or []) + 1)
    try:
        egress_id = await _start_egress(call, key)
    except Exception as e:
        logger.warning(f"[recording] could not resume for call {call.id}: {e}")
        call_service.record_event(db, call, "recording_failed", payload={"error": str(e)[:300], "on": "resume"})
        raise RecordingError("Could not resume the recording")
    paused_seconds = (datetime.utcnow() - call.recording_paused_at).total_seconds() if call.recording_paused_at else None
    call.recording_egress_id = egress_id
    call.recording_status = "recording"
    call.recording_paused_at = None
    _add_part(call, egress_id, key)
    db.commit()
    payload = {"reason": reason or None, "paused_seconds": round(paused_seconds or 0), "automatic": user_id is None}
    call_service.record_event(db, call, "recording_resumed", actor_type="agent" if user_id else "system",
                              actor_user_id=user_id, payload=payload)
    log_action(db, call.company_id, user_id, "recording.resumed", entity_type="voice_call", entity_id=call.id,
               changes=payload)
    db.commit()
    return {"recording_status": call.recording_status}


async def resume_if_paused(db: Session, call: VoiceCall, reason: str) -> None:
    """Transfers: the next agent's part of the call is always recorded."""
    if call.recording_status == "paused":
        try:
            await resume(db, call, None, reason=reason)
        except RecordingError as e:
            logger.warning(f"[recording] call {call.id}: automatic resume failed: {e}")


def on_call_ended(db: Session, call: VoiceCall) -> None:
    """Call ended while paused: the parts recorded so far are the recording."""
    if call.recording_status != "paused":
        return
    parts = call.recording_parts or []
    call.recording_status = "completed" if any(p.get("status") in ("completed", "stopping") for p in parts) else "failed"
    call.recording_paused_at = None
    call.recording_ended_at = datetime.utcnow()
    db.commit()


def on_egress_finished(db: Session, info) -> None:
    """Egress webhook: mark that part complete (with duration / size) or failed; then the whole recording."""
    call = (db.query(VoiceCall).filter(VoiceCall.recording_egress_id == info.egress_id).first()
            or db.query(VoiceCall).filter(VoiceCall.recording_parts.contains([{"egress_id": info.egress_id}])).first())
    if not call:
        return
    ok = info.status == egress_proto.EgressStatus.EGRESS_COMPLETE
    result = info.file_results[0] if info.file_results else None
    fields = {"status": "completed" if ok else "failed"}
    if result:
        fields["duration"] = (result.duration or 0) / 1e9
        if result.filename:
            fields["key"] = result.filename
    if not call.recording_parts:  # recorded before parts existed
        _add_part(call, info.egress_id, (result.filename if result else None) or call.recording_object_key)
    _update_part(call, info.egress_id, **fields)
    parts = call.recording_parts
    call.recording_duration_secs = sum(p.get("duration") or 0 for p in parts if p.get("status") == "completed") or None
    if parts and parts[0].get("key"):
        call.recording_object_key = parts[0]["key"]
    # a pause stops a part while the call goes on; otherwise this was the last part
    still_paused = call.recording_status == "paused" and call.status in call_service.ACTIVE_STATUSES
    if not still_paused and info.egress_id == call.recording_egress_id:
        call.recording_status = "completed" if any(p.get("status") == "completed" for p in parts) else "failed"
        call.recording_ended_at = datetime.utcnow()
        call.recording_paused_at = None
    db.commit()
    call_service.record_event(db, call, "recording_completed" if ok else "recording_failed",
                              payload={"error": info.error or None, "size": result.size if result else None,
                                       "part": next((i + 1 for i, p in enumerate(parts) if p.get("egress_id") == info.egress_id), None)})


def part_keys(call: VoiceCall) -> list[str]:
    keys = [p["key"] for p in (call.recording_parts or []) if p.get("key") and p.get("status") in ("completed", "stopping")]
    return keys or ([call.recording_object_key] if call.recording_object_key else [])


def access_urls(db: Session, call: VoiceCall, user_id: int, download: bool) -> list[str]:
    """Short-lived links to the recording (one per part, in order); the access is logged as a call event and in the audit log."""
    from app.core.audit import log_action
    from app.core.object_storage import BUCKET_NAME, s3_client

    keys = part_keys(call)
    urls = []
    for i, key in enumerate(keys, start=1):
        params = {"Bucket": BUCKET_NAME, "Key": key}
        if download:
            name = f"call-{call.id}.ogg" if len(keys) == 1 else f"call-{call.id}-part{i}.ogg"
            params["ResponseContentDisposition"] = f'attachment; filename="{name}"'
        urls.append(s3_client.generate_presigned_url("get_object", Params=params, ExpiresIn=300))
    action = "download" if download else "listen"
    call_service.record_event(db, call, f"recording_{action}", actor_type="agent", actor_user_id=user_id)
    log_action(db, call.company_id, user_id, f"recording.{action}", entity_type="voice_call", entity_id=call.id)
    db.commit()
    return urls
