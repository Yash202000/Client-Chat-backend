from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, HTTPException, Query, status
from app.services.connection_manager import manager
from app.models import user as models_user
from app.core.database import SessionLocal
from app.services import user_service
from jose import JWTError, jwt
from app.core.config import settings
from typing import Optional
import json
import logging
logger = logging.getLogger(__name__)

router = APIRouter()

async def authenticate_websocket_user(websocket: WebSocket, token: Optional[str]) -> Optional[models_user.User]:
    """Authenticate user for WebSocket connection without holding DB session. Returns None if auth fails."""
    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Authentication token missing")
        return None

    db = SessionLocal()
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        email: str = payload.get("sub")
        if not email:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid token")
            return None

        user = user_service.get_user_by_email(db, email=email)
        if not user:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="User not found")
            return None
        return user
    except JWTError:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Could not validate credentials")
        return None
    finally:
        db.close()

@router.websocket("/{company_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    company_id: int,
    token: Optional[str] = Query(None)
):
    # Convert company_id to string for consistent channel naming
    channel_id = str(company_id)

    # Accept connection first
    await manager.connect(websocket, channel_id, "user")

    # Then authenticate (will close connection if auth fails)
    current_user = await authenticate_websocket_user(websocket, token)
    if not current_user:
        return

    if current_user.company_id != company_id:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Company mismatch")
        return

    # Cancel any pending offline task (user reconnected)
    user_service.cancel_pending_offline(current_user.id)

    # Update user presence status to online
    db = SessionLocal()
    try:
        user_service.update_user_presence(db, user_id=current_user.id, status="online")

        # Broadcast presence update to all company users
        presence_update = json.dumps({
            "type": "presence_update",
            "payload": {
                "user_id": current_user.id,
                "status": "online"
            }
        })
        await manager.broadcast(presence_update, channel_id)
    finally:
        db.close()


    try:
        while True:
            data = await websocket.receive_text()

            # Handle ping/pong messages to keep connection alive
            try:
                message = json.loads(data)
                if message.get("type") == "ping":
                    # Respond to heartbeat ping with pong
                    await websocket.send_text(json.dumps({"type": "pong"}))
                    continue
            except json.JSONDecodeError:
                logger.exception("Unexpected error")

    except WebSocketDisconnect:
        manager.disconnect(websocket, channel_id)

        # Mark user as inactive in DB so schedule_offline_update won't skip the "online" check
        db = SessionLocal()
        try:
            user_service.update_user_presence(db, user_id=current_user.id, status="inactive")
        finally:
            db.close()

        # Schedule delayed offline update (allows reconnection within grace period)
        await user_service.schedule_offline_update(SessionLocal, current_user.id)

        # Broadcast inactive (not offline/red) — corrected to online if user reconnects
        presence_update = json.dumps({
            "type": "presence_update",
            "payload": {
                "user_id": current_user.id,
                "status": "inactive"
            }
        })
        await manager.broadcast(presence_update, channel_id)

    except Exception as e:
        manager.disconnect(websocket, channel_id)

        # Schedule delayed offline update on error (allows reconnection within grace period)
        try:
            db = SessionLocal()
            try:
                user_service.update_user_presence(db, user_id=current_user.id, status="inactive")
            finally:
                db.close()

            await user_service.schedule_offline_update(SessionLocal, current_user.id)

            presence_update = json.dumps({
                "type": "presence_update",
                "payload": {
                    "user_id": current_user.id,
                    "status": "inactive"
                }
            })
            await manager.broadcast(presence_update, channel_id)
        except Exception as broadcast_error:
            logger.exception(broadcast_error)

