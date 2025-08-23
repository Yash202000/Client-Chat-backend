
from fastapi import WebSocket, APIRouter, Depends, WebSocketDisconnect, Query, status
from typing import Dict, List
from sqlalchemy.orm import Session
from app.core.database import SessionLocal
from app.core.dependencies import get_db
from app.models import User
from app.core.auth import get_current_user

router = APIRouter()

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[int, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, channel_id: int):
        await websocket.accept()
        if channel_id not in self.active_connections:
            self.active_connections[channel_id] = []
        self.active_connections[channel_id].append(websocket)

    def disconnect(self, websocket: WebSocket, channel_id: int):
        if channel_id in self.active_connections:
            self.active_connections[channel_id].remove(websocket)

    async def broadcast(self, message: str, channel_id: int):
        if channel_id in self.active_connections:
            for connection in self.active_connections[channel_id]:
                await connection.send_text(message)

manager = ConnectionManager()

@router.websocket("/ws/chat/{channel_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    channel_id: int,
):
    print(f"Attempting to connect to WebSocket for channel {channel_id}")

    await manager.connect(websocket, channel_id)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket, channel_id)
