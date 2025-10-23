import json
from typing import Any, Dict, List
from fastapi import WebSocket


class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, List[Dict[str, Any]]] = {}

    async def connect(self, websocket: WebSocket, session_id: str, user_type: str):
        await websocket.accept()
        if session_id not in self.active_connections:
            self.active_connections[session_id] = []
        self.active_connections[session_id].append({"websocket": websocket, "user_type": user_type})
        print(f"Connected: {user_type} to session {session_id}. Total connections for session: {len(self.active_connections[session_id])}")

    def disconnect(self, websocket: WebSocket, session_id: str):
        print(f"[disconnect] Attempting to disconnect from channel '{session_id}'")
        if session_id in self.active_connections:
            connection_to_remove = next((c for c in self.active_connections[session_id] if c["websocket"] == websocket), None)
            if connection_to_remove:
                self.active_connections[session_id].remove(connection_to_remove)
                print(f"[disconnect] ✅ Disconnected {connection_to_remove['user_type']} from channel '{session_id}'. Remaining: {len(self.active_connections.get(session_id, []))}")
                if not self.active_connections[session_id]:
                    del self.active_connections[session_id]
                    print(f"[disconnect] 🗑️ Removed empty channel '{session_id}'")
                print(f"[disconnect] 📊 Active channels after disconnect: {list(self.active_connections.keys())}")
        else:
            print(f"[disconnect] ⚠️ Channel '{session_id}' not found in active connections")

    async def broadcast_to_session(self, session_id: str, message: str, sender_type: str):
        print(f"[ConnectionManager] Broadcasting to session {session_id}. Message: {message[:50]}...")
        if session_id in self.active_connections:
            message_data = json.loads(message)
            if message_data.get('message_type') == 'note':
                connections_to_send = [c for c in self.active_connections[session_id] if c["user_type"] == "agent"]
                print(f"[ConnectionManager] Sending note to {len(connections_to_send)} agent connections in session {session_id}")
            else:
                connections_to_send = self.active_connections[session_id]
                print(f"[ConnectionManager] Sending message to {len(connections_to_send)} connections in session {session_id}")
            
            for connection in connections_to_send:
                try:
                    await connection["websocket"].send_text(message)
                    print(f"[ConnectionManager] Sent message to websocket: {connection["websocket"]}")
                except Exception as e:
                    print(f"[ConnectionManager] Error sending message to websocket: {e}")
                    # Optionally remove broken connection
                    # self.active_connections[session_id].remove(connection)
        else:
            print(f"[ConnectionManager] No active connections for session {session_id}")
    
    async def broadcast(self, message: str, channel_id: str):
        print(f"[broadcast] Attempting to broadcast to channel '{channel_id}' (type: {type(channel_id).__name__})")
        print(f"[broadcast] Active connection keys: {list(self.active_connections.keys())}")
        print(f"[broadcast] Active connection key types: {[type(k).__name__ for k in self.active_connections.keys()]}")

        if channel_id in self.active_connections:
            print(f"[broadcast] ✅ Found {len(self.active_connections[channel_id])} connections for channel {channel_id}")
            for connection in self.active_connections[channel_id]:
                await connection["websocket"].send_text(message)
                print(f"[broadcast] Sent to {connection['user_type']} via {connection['websocket']}")
        else:
            print(f"[broadcast] ❌ No connections found for channel '{channel_id}'")

    async def broadcast_to_company(self, company_id: int, message: str):
        """
        Broadcast a message to all users connected to a company channel.
        This is an alias for broadcast() with company_id converted to string.
        """
        channel_id = str(company_id)
        print(f"[broadcast_to_company] Broadcasting to company {company_id} (channel: '{channel_id}')")
        await self.broadcast(message, channel_id)

    async def disconnect_all(self):
        print("[ConnectionManager] Disconnecting all clients...")
        for session_id in list(self.active_connections.keys()):
            for connection in self.active_connections[session_id]:
                try:
                    await connection["websocket"].close(code=1000)
                except Exception as e:
                    print(f"Error closing websocket for session {session_id}: {e}")
        self.active_connections.clear()
        print("[ConnectionManager] All clients disconnected.")

    def has_user_connection(self, session_id: str) -> bool:
        """
        Checks if a session has at least one active user (not agent) connection.
        Returns True if there's an active user connection, False otherwise.
        """
        if session_id not in self.active_connections:
            return False

        user_connections = [c for c in self.active_connections[session_id] if c["user_type"] == "user"]
        return len(user_connections) > 0

    def get_connection_status(self, session_id: str) -> bool:
        """
        Gets the real-time connection status for a session.
        Returns True if client is connected, False otherwise.
        """
        return self.has_user_connection(session_id)

manager = ConnectionManager()
