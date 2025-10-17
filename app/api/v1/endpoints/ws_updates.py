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
    print(f"[ws_updates] Attempting WebSocket connection for company_id: {company_id}, user: {current_user.email}")
    if current_user.company_id != company_id:
        print(f"[ws_updates] Connection rejected: User company_id ({current_user.company_id}) does not match path company_id ({company_id})")
        await websocket.close(code=403)
        return

    # Convert company_id to string for consistent channel naming
    channel_id = str(company_id)
    await manager.connect(websocket, channel_id, "user")
    print(f"[ws_updates] WebSocket connection established for company_id: {company_id} (channel: {channel_id})")
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket, channel_id)
        print(f"[ws_updates] WebSocket connection closed for company_id: {company_id}")
