import asyncio
import json
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple
from fastapi import WebSocket
import logging
logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, List[Dict[str, Any]]] = {}
        # Track last activity timestamp for each websocket: {session_id: {websocket_id: timestamp}}
        self.last_activity: Dict[str, Dict[int, float]] = {}
        # Redis fan-out (optional). When enabled, text broadcasts are published to Redis and
        # every process (including this one) delivers them to its own local sockets.
        self._redis = None
        self._fanout_channel: Optional[str] = None
        self._subscriber_task: Optional[asyncio.Task] = None
        self.instance_id = uuid.uuid4().hex[:8]

    # ------------------------------------------------------------------ fan-out

    @property
    def fanout_enabled(self) -> bool:
        return self._redis is not None

    async def start_fanout(self, channel: str, subscribe: bool = True):
        """Enable Redis fan-out (REDIS_URL or Redis Sentinel). Processes without websockets (e.g. the voice
        process) pass subscribe=False."""
        from app.core.redis_client import async_redis, redis_enabled

        if not redis_enabled() or self._redis is not None:
            return
        client = async_redis(decode_responses=True)
        await client.ping()
        self._redis = client
        self._fanout_channel = channel
        if subscribe:
            self._subscriber_task = asyncio.create_task(self._fanout_listener())
        logger.info(f"[ws-fanout] enabled on {channel} (instance {self.instance_id}, subscribe={subscribe})")

    async def stop_fanout(self):
        if self._subscriber_task:
            self._subscriber_task.cancel()
            try:
                await self._subscriber_task
            except asyncio.CancelledError:
                pass
            self._subscriber_task = None
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None

    async def _publish(self, envelope: Dict[str, Any]) -> bool:
        try:
            await self._redis.publish(self._fanout_channel, json.dumps(envelope))
            return True
        except Exception:
            logger.exception("[ws-fanout] publish failed, delivering locally only")
            return False

    async def _fanout_listener(self):
        while True:
            try:
                pubsub = self._redis.pubsub()
                await pubsub.subscribe(self._fanout_channel)
                async for item in pubsub.listen():
                    if item.get("type") != "message":
                        continue
                    try:
                        env = json.loads(item["data"])
                        if env.get("op") == "session":
                            await self._local_broadcast_to_session(env["target"], env["message"])
                        else:
                            await self._local_broadcast(env["message"], env["target"])
                    except Exception:
                        logger.exception("[ws-fanout] bad envelope")
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("[ws-fanout] listener error, reconnecting in 2s")
                await asyncio.sleep(2)

    async def connect(self, websocket: WebSocket, session_id: str, user_type: str, connection_type: str = "chat"):
        await websocket.accept()
        if session_id not in self.active_connections:
            self.active_connections[session_id] = []
            self.last_activity[session_id] = {}

        self.active_connections[session_id].append({"websocket": websocket, "user_type": user_type, "connection_type": connection_type, "user_id": None})

        # Initialize activity timestamp
        ws_id = id(websocket)
        self.last_activity[session_id][ws_id] = time.time()

    def tag_user(self, websocket: WebSocket, session_id: str, user_id: int):
        """Associate an authenticated user_id with a connection, once known post-accept."""
        if session_id in self.active_connections:
            for connection in self.active_connections[session_id]:
                if connection["websocket"] == websocket:
                    connection["user_id"] = user_id
                    break

    def has_user_connection_by_id(self, session_id: str, user_id: int) -> bool:
        """Check whether a specific user still holds any other active connection in this channel."""
        if session_id not in self.active_connections:
            return False
        return any(c.get("user_id") == user_id for c in self.active_connections[session_id])

    def disconnect(self, websocket: WebSocket, session_id: str):
        if session_id in self.active_connections:
            connection_to_remove = next((c for c in self.active_connections[session_id] if c["websocket"] == websocket), None)
            if connection_to_remove:
                self.active_connections[session_id].remove(connection_to_remove)

                # Remove activity tracking
                ws_id = id(websocket)
                if session_id in self.last_activity and ws_id in self.last_activity[session_id]:
                    del self.last_activity[session_id][ws_id]

                if not self.active_connections[session_id]:
                    del self.active_connections[session_id]
                    if session_id in self.last_activity:
                        del self.last_activity[session_id]
        else:
            pass

    async def broadcast_to_session(self, session_id: str, message: str, sender_type: str = ""):
        if self.fanout_enabled and await self._publish({"op": "session", "target": session_id, "message": message}):
            return
        await self._local_broadcast_to_session(session_id, message)

    async def _local_broadcast_to_session(self, session_id: str, message: str):
        if session_id in self.active_connections:
            message_data = json.loads(message)
            if message_data.get('message_type') == 'note':
                connections_to_send = [c for c in self.active_connections[session_id] if c["user_type"] == "agent"]
            else:
                connections_to_send = self.active_connections[session_id]
            
            failed_connections = []

            for connection in connections_to_send:
                try:
                    await connection["websocket"].send_text(message)
                except Exception as e:
                    failed_connections.append(connection)

            # Clean up dead connections after iteration
            for failed_conn in failed_connections:
                try:
                    self.active_connections[session_id].remove(failed_conn)
                except ValueError:
                    logger.exception("Unexpected error")

            # Clean up empty session
            if session_id in self.active_connections and not self.active_connections[session_id]:
                del self.active_connections[session_id]
        else:
            pass
    
    async def broadcast(self, message: str, channel_id: str):
        if self.fanout_enabled and await self._publish({"op": "channel", "target": channel_id, "message": message}):
            return
        await self._local_broadcast(message, channel_id)

    async def _local_broadcast(self, message: str, channel_id: str):
        if channel_id in self.active_connections:

            # Track connections that fail so we can remove them after iteration
            failed_connections = []

            for connection in self.active_connections[channel_id]:
                try:
                    await connection["websocket"].send_text(message)
                except Exception as e:
                    failed_connections.append(connection)

            # Clean up dead connections after iteration
            for failed_conn in failed_connections:
                try:
                    if channel_id in self.active_connections:
                        self.active_connections[channel_id].remove(failed_conn)
                except ValueError:
                    logger.exception("Unexpected error")

            # Clean up empty channel
            if channel_id in self.active_connections and not self.active_connections[channel_id]:
                del self.active_connections[channel_id]
        else:
            pass

    async def broadcast_bytes_to_session(self, session_id: str, data: bytes):
        """
        Broadcast binary data (audio) to voice connections only for a session.
        Used for sending TTS audio to voice WebSocket connections.

        Args:
            session_id: The session ID to broadcast to
            data: Binary data (audio bytes) to send
        """
        if session_id in self.active_connections:
            # Filter for voice connections only
            voice_connections = [c for c in self.active_connections[session_id] if c.get("connection_type") == "voice"]

            failed_connections = []

            for connection in voice_connections:
                try:
                    await connection["websocket"].send_bytes(data)
                except Exception as e:
                    failed_connections.append(connection)

            # Clean up dead connections after iteration
            for failed_conn in failed_connections:
                try:
                    self.active_connections[session_id].remove(failed_conn)
                except ValueError:
                    logger.exception("Unexpected error")
        else:
            pass

    def register(self, websocket: WebSocket, session_id: str, user_type: str, connection_type: str = "notifications"):
        """Register an already-accepted WebSocket without calling accept() again."""
        if session_id not in self.active_connections:
            self.active_connections[session_id] = []
            self.last_activity[session_id] = {}
        self.active_connections[session_id].append({
            "websocket": websocket,
            "user_type": user_type,
            "connection_type": connection_type,
        })
        self.last_activity[session_id][id(websocket)] = time.time()

    async def broadcast_to_company(self, company_id: int, message: str):
        """
        Broadcast a message to all users connected to a company channel.
        This is an alias for broadcast() with company_id converted to string.
        """
        channel_id = str(company_id)
        await self.broadcast(message, channel_id)

    async def broadcast_to_user(self, user_id: int, message: str):
        """
        Broadcast a message to a specific user across all their active sessions.
        Useful for notifications like incoming calls.

        Args:
            user_id: The user ID to send the message to
            message: The message to send
        """
        user_channel = f"user_{user_id}"
        await self.broadcast(message, user_channel)

    async def disconnect_all(self):
        for session_id in list(self.active_connections.keys()):
            for connection in self.active_connections[session_id]:
                try:
                    await connection["websocket"].close(code=1000)
                except Exception as e:
                    logger.exception(e)
        self.active_connections.clear()

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

    def update_activity(self, session_id: str, websocket: WebSocket):
        """Update the last activity timestamp for a specific websocket connection"""
        if session_id in self.last_activity:
            ws_id = id(websocket)
            self.last_activity[session_id][ws_id] = time.time()

    def is_preview_session(self, session_id: str) -> bool:
        """Check if session is a preview session based on ID prefix"""
        return session_id.startswith("preview_session_")

    def get_session_timeout(self, session_id: str) -> int:
        """Get timeout in seconds based on session type"""
        from app.core.config import settings
        if self.is_preview_session(session_id):
            return settings.WS_PREVIEW_SESSION_TIMEOUT
        return settings.WS_REGULAR_SESSION_TIMEOUT

    def get_inactive_connections(self) -> List[Tuple[str, WebSocket, float]]:
        """
        Returns list of (session_id, websocket, idle_time) for connections
        that have exceeded their timeout period
        """
        current_time = time.time()
        inactive = []

        for session_id in list(self.active_connections.keys()):
            timeout = self.get_session_timeout(session_id)

            if session_id in self.last_activity:
                for connection in self.active_connections[session_id]:
                    ws_id = id(connection["websocket"])
                    last_seen = self.last_activity[session_id].get(ws_id, current_time)
                    idle_time = current_time - last_seen

                    if idle_time > timeout:
                        inactive.append((session_id, connection["websocket"], idle_time))

        return inactive

manager = ConnectionManager()
