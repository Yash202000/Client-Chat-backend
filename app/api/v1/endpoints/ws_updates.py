from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, HTTPException, Query, status
from app.services.connection_manager import manager
from app.models import user as models_user
from app.core.database import SessionLocal
from app.services import user_service
from jose import JWTError, jwt
from app.core.config import settings
from typing import Optional
import json

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

@router.websocket("/ws/{company_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    company_id: int,
    token: Optional[str] = Query(None)
):
    # Convert company_id to string for consistent channel naming
    channel_id = str(company_id)
    print(f"[ws_updates] 🔌 Connecting to channel: '{channel_id}' (type: {type(channel_id).__name__})")

    # Accept connection first
    await manager.connect(websocket, channel_id, "user")
    print(f"[ws_updates] ✅ WebSocket connection established for company_id: {company_id} (channel: '{channel_id}')")

    # Then authenticate (will close connection if auth fails)
    current_user = await authenticate_websocket_user(websocket, token)
    if not current_user:
        return

    print(f"[ws_updates] 📡 Authenticated user: {current_user.email}")
    if current_user.company_id != company_id:
        print(f"[ws_updates] ❌ Connection rejected: User company_id ({current_user.company_id}) does not match path company_id ({company_id})")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Company mismatch")
        return

    print(f"[ws_updates] 📊 Current active channels: {list(manager.active_connections.keys())}")

    try:
        while True:
            data = await websocket.receive_text()

            # Handle ping/pong messages to keep connection alive
            try:
                message = json.loads(data)
                if message.get("type") == "ping":
                    # Respond to heartbeat ping with pong
                    await websocket.send_text(json.dumps({"type": "pong"}))
                    print(f"[ws_updates] 💓 Heartbeat ping received, sent pong")
                    continue
            except json.JSONDecodeError:
                # Not a JSON message, just log it
                print(f"[ws_updates] 📨 Received non-JSON data from client: {data[:100]}")

    except WebSocketDisconnect:
        print(f"[ws_updates] 🔌 Client disconnected from channel '{channel_id}'")
        manager.disconnect(websocket, channel_id)
        print(f"[ws_updates] ❌ WebSocket connection closed for company_id: {company_id}")
        print(f"[ws_updates] 📊 Remaining channels: {list(manager.active_connections.keys())}")
    except Exception as e:
        print(f"[ws_updates] ⚠️ Error in WebSocket: {e}")
        manager.disconnect(websocket, channel_id)
        print(f"[ws_updates] 📊 Remaining channels: {list(manager.active_connections.keys())}")
