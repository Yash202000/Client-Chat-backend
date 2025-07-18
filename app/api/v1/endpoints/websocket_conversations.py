from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, Query
from sqlalchemy.orm import Session
from app.core.dependencies import get_db
from app.services import chat_service, agent_execution_service
from app.schemas import chat_message as schemas_chat_message
import json
from typing import List, Dict, Any

router = APIRouter()

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, List[Dict[str, Any]]] = {}

    async def connect(self, websocket: WebSocket, session_id: str, user_type: str):
        await websocket.accept()
        if session_id not in self.active_connections:
            self.active_connections[session_id] = []
        self.active_connections[session_id].append({"websocket": websocket, "user_type": user_type})

    def disconnect(self, websocket: WebSocket, session_id: str):
        if session_id in self.active_connections:
            connection_to_remove = next((c for c in self.active_connections[session_id] if c["websocket"] == websocket), None)
            if connection_to_remove:
                self.active_connections[session_id].remove(connection_to_remove)
                if not self.active_connections[session_id]:
                    del self.active_connections[session_id]

    async def broadcast_to_session(self, session_id: str, message: str, sender_type: str):
        if session_id in self.active_connections:
            message_data = json.loads(message)
            if message_data.get('message_type') == 'note':
                connections_to_send = [c for c in self.active_connections[session_id] if c["user_type"] == "agent"]
            else:
                connections_to_send = self.active_connections[session_id]
            
            for connection in connections_to_send:
                await connection["websocket"].send_text(message)

manager = ConnectionManager()

@router.websocket("/{company_id}/{agent_id}/{session_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    company_id: int,
    agent_id: int,
    session_id: str,
    user_type: str = Query(...), # 'user' or 'agent'
    db: Session = Depends(get_db)
):
    await manager.connect(websocket, session_id, user_type)
    try:
        while True:
            data = await websocket.receive_text()
            if not data:
                continue
            try:
                message_data = json.loads(data)
            except json.JSONDecodeError:
                print(f"Received invalid JSON from session #{session_id}: {data}")
                continue
            
            sender = message_data.get('sender')
            
            chat_message = schemas_chat_message.ChatMessageCreate(message=message_data['message'], message_type=message_data['message_type'])
            db_message = chat_service.create_chat_message(db, chat_message, agent_id, session_id, company_id, sender)
            
            # Use Pydantic's .json() method for correct serialization
            await manager.broadcast_to_session(session_id, schemas_chat_message.ChatMessage.from_orm(db_message).json(), sender)

            if sender == 'user':
                agent_response_text = agent_execution_service.generate_agent_response(
                    db, agent_id, session_id, company_id, message_data['message']
                )
                
                agent_message = schemas_chat_message.ChatMessageCreate(message=agent_response_text, message_type="message")
                
                db_agent_message = chat_service.create_chat_message(db, agent_message, agent_id, session_id, company_id, "agent")

                # Use Pydantic's .json() method for correct serialization
                await manager.broadcast_to_session(session_id, schemas_chat_message.ChatMessage.from_orm(db_agent_message).json(), "agent")

    except WebSocketDisconnect:
        manager.disconnect(websocket, session_id)
        print(f"Client in session #{session_id} disconnected")