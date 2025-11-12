"""
WebSocket Session Cleanup Service

This service provides periodic cleanup functionality for inactive WebSocket sessions.
It identifies connections that have exceeded their timeout period and gracefully closes them.
"""

import asyncio
import logging
from app.services.connection_manager import ConnectionManager
from app.core.config import settings

logger = logging.getLogger(__name__)


async def cleanup_inactive_sessions(manager: ConnectionManager):
    """
    Periodic task to clean up inactive WebSocket sessions.
    Called by APScheduler every WS_CLEANUP_INTERVAL seconds.

    Args:
        manager: ConnectionManager instance to check for inactive connections

    Features:
        - Different timeouts for preview vs regular sessions
        - Graceful disconnect with close reason
        - Comprehensive logging for monitoring
    """
    try:
        inactive_connections = manager.get_inactive_connections()

        if not inactive_connections:
            logger.debug("No inactive connections to clean up")
            return

        logger.info(f"Found {len(inactive_connections)} inactive connections to clean up")

        for session_id, websocket, idle_time in inactive_connections:
            try:
                session_type = "preview" if manager.is_preview_session(session_id) else "regular"
                logger.info(
                    f"Closing inactive {session_type} session: {session_id} "
                    f"(idle for {idle_time:.0f}s)"
                )

                # Try to send close frame, but don't fail if already closed
                try:
                    # Check if WebSocket is still in a state where we can close it
                    if hasattr(websocket, 'client_state'):
                        from starlette.websockets import WebSocketState
                        if websocket.client_state == WebSocketState.CONNECTED:
                            await websocket.close(
                                code=1000,
                                reason=f"Session timeout after {idle_time:.0f}s of inactivity"
                            )
                    else:
                        # Fallback for older versions or different implementations
                        await websocket.close(
                            code=1000,
                            reason=f"Session timeout after {idle_time:.0f}s of inactivity"
                        )
                except Exception as close_error:
                    # WebSocket already closed, that's fine - just log it
                    logger.debug(f"WebSocket already closed for session {session_id}: {close_error}")

                # Clean up from manager (do this even if close failed)
                manager.disconnect(websocket, session_id)

            except Exception as e:
                logger.error(f"Error handling inactive connection for session {session_id}: {e}")

        logger.info(f"Cleanup complete. Closed {len(inactive_connections)} inactive connections")

    except Exception as e:
        logger.error(f"Error in cleanup_inactive_sessions: {e}")
