from typing import Dict, List
from fastapi import WebSocket

class ConnectionManager:
    def __init__(self):
        # Structure: {company_id: [WebSocket, WebSocket, ...]}
        self.active_connections: Dict[int, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, company_id: int):
        await websocket.accept()
        if company_id not in self.active_connections:
            self.active_connections[company_id] = []
        self.active_connections[company_id].append(websocket)

    def disconnect(self, websocket: WebSocket, company_id: int):
        if company_id in self.active_connections:
            self.active_connections[company_id].remove(websocket)

    async def broadcast_to_company(self, company_id: int, message: str):
        if company_id in self.active_connections:
            for connection in self.active_connections[company_id]:
                await connection.send_text(message)

manager = ConnectionManager()
