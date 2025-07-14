from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from sqlalchemy.orm import Session
from app.core.dependencies import get_db
from app.services import chat_service, agent_execution_service
from app.schemas import chat_message as schemas_chat_message

router = APIRouter()

class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, session_id: str):
        await websocket.accept()
        self.active_connections[session_id] = websocket

    def disconnect(self, session_id: str):
        if session_id in self.active_connections:
            del self.active_connections[session_id]

    async def send_personal_message(self, message: str, websocket: WebSocket):
        await websocket.send_text(message)

    async def broadcast(self, message: str):
        for connection in self.active_connections.values():
            await connection.send_text(message)

manager = ConnectionManager()

@router.websocket("/{company_id}/{agent_id}/{session_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    company_id: int,
    agent_id: int,
    session_id: str,
    db: Session = Depends(get_db)
):
    await manager.connect(websocket, session_id)
    try:
        while True:
            data = await websocket.receive_text()
            
            # 1. Save user's message to the database
            user_message = schemas_chat_message.ChatMessageCreate(message=data, message_type="message")
            chat_service.create_chat_message(db, user_message, agent_id, session_id, company_id, "user")

            # 2. Get agent's response using the new execution service
            agent_response_text = agent_execution_service.generate_agent_response(
                db, agent_id, session_id, company_id, data
            )

            # 3. Save agent's response to the database
            agent_message = schemas_chat_message.ChatMessageCreate(message=agent_response_text, message_type="message")
            chat_service.create_chat_message(db, agent_message, agent_id, session_id, company_id, "agent")

            # 4. Send agent's response back to the user
            await manager.send_personal_message(agent_response_text, websocket)

    except WebSocketDisconnect:
        manager.disconnect(session_id)
        print(f"Client #{session_id} disconnected")