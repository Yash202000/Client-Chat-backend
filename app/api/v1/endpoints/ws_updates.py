from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, HTTPException
from app.services.connection_manager import manager
from app.core.dependencies import get_current_user_from_ws
from app.models import user as models_user

router = APIRouter()

@router.websocket("/ws/{company_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    company_id: int,
    current_user: models_user.User = Depends(get_current_user_from_ws)
):
    print(f"[ws_updates] 📡 Attempting WebSocket connection for company_id: {company_id}, user: {current_user.email}")
    if current_user.company_id != company_id:
        print(f"[ws_updates] ❌ Connection rejected: User company_id ({current_user.company_id}) does not match path company_id ({company_id})")
        await websocket.close(code=403)
        return

    # Convert company_id to string for consistent channel naming
    channel_id = str(company_id)
    print(f"[ws_updates] 🔌 Connecting to channel: '{channel_id}' (type: {type(channel_id).__name__})")
    await manager.connect(websocket, channel_id, "user")
    print(f"[ws_updates] ✅ WebSocket connection established for company_id: {company_id} (channel: '{channel_id}')")
    print(f"[ws_updates] 📊 Current active channels: {list(manager.active_connections.keys())}")

    try:
        while True:
            data = await websocket.receive_text()
            print(f"[ws_updates] 📨 Received data from client: {data[:100]}")
    except WebSocketDisconnect:
        print(f"[ws_updates] 🔌 Client disconnected from channel '{channel_id}'")
        manager.disconnect(websocket, channel_id)
        print(f"[ws_updates] ❌ WebSocket connection closed for company_id: {company_id}")
        print(f"[ws_updates] 📊 Remaining channels: {list(manager.active_connections.keys())}")
    except Exception as e:
        print(f"[ws_updates] ⚠️ Error in WebSocket: {e}")
        manager.disconnect(websocket, channel_id)
        print(f"[ws_updates] 📊 Remaining channels: {list(manager.active_connections.keys())}")
