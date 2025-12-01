import asyncio
import json
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from app.core.database import SessionLocal
from app.crud import crud_video_call, crud_chat, crud_notification
from app.services.connection_manager import manager
import logging

logger = logging.getLogger(__name__)

class CallTimeoutService:
    """Background service to check for timed-out video calls"""

    def __init__(self, check_interval: int = 10, timeout_seconds: int = 30):
        """
        Initialize the call timeout service

        Args:
            check_interval: How often to check for timeouts (in seconds)
            timeout_seconds: How long before a call is considered timed out (in seconds)
        """
        self.check_interval = check_interval
        self.timeout_seconds = timeout_seconds
        self.is_running = False

    async def check_timeouts(self):
        """Check for calls that have timed out and mark them as missed"""
        db: Session = SessionLocal()
        try:
            # Find all calls in "ringing" status
            timeout_threshold = datetime.utcnow() - timedelta(seconds=self.timeout_seconds)

            from app.models.video_call import VideoCall
            timed_out_calls = db.query(VideoCall).filter(
                VideoCall.status == "ringing",
                VideoCall.started_at <= timeout_threshold
            ).all()

            for call in timed_out_calls:
                logger.info(f"Call {call.id} timed out (channel {call.channel_id})")

                # Mark call as missed
                crud_video_call.mark_call_as_missed(db, video_call_id=call.id)

                # Create system message in chat
                try:
                    # Get caller info
                    from app.models.user import User
                    caller = db.query(User).filter(User.id == call.created_by_id).first()
                    caller_name = caller.first_name or caller.email if caller else "Unknown"

                    system_message_content = f"📵 Missed call from {caller_name}"
                    crud_chat.create_system_message(
                        db=db,
                        channel_id=call.channel_id,
                        content=system_message_content,
                        extra_data={"call_id": call.id, "call_status": "missed", "caller_id": call.created_by_id}
                    )
                except Exception as e:
                    logger.error(f"Failed to create system message for missed call: {e}")

                # Create notifications for all channel members (except caller)
                try:
                    from app.models.user import User
                    from app.models.channel_membership import ChannelMembership
                    caller = db.query(User).filter(User.id == call.created_by_id).first()
                    caller_name = caller.first_name or caller.email if caller else "Unknown"

                    # Get all channel members
                    members = db.query(ChannelMembership).filter(
                        ChannelMembership.channel_id == call.channel_id
                    ).all()

                    for member in members:
                        crud_notification.create_missed_call_notification(
                            db=db,
                            user_id=member.user_id,
                            call_id=call.id,
                            channel_id=call.channel_id,
                            caller_id=call.created_by_id,
                            caller_name=caller_name
                        )

                    logger.info(f"Created missed call notifications for {len(members)} members")
                except Exception as e:
                    logger.error(f"Failed to create notifications for missed call: {e}")

                # Broadcast timeout message to all channel members
                try:
                    await manager.broadcast(
                        json.dumps({
                            "type": "call_missed",
                            "call_id": call.id,
                            "room_name": call.room_name,
                            "channel_id": call.channel_id,
                            "caller_id": call.created_by_id,
                        }),
                        str(call.channel_id)
                    )
                    logger.info(f"Broadcasted call_missed for call {call.id}")
                except Exception as e:
                    logger.error(f"Failed to broadcast call_missed: {e}")

        except Exception as e:
            logger.error(f"Error checking call timeouts: {e}")
        finally:
            db.close()

    async def start(self):
        """Start the background timeout checking service"""
        self.is_running = True
        logger.info(f"Call timeout service started (check interval: {self.check_interval}s, timeout: {self.timeout_seconds}s)")

        while self.is_running:
            try:
                await self.check_timeouts()
            except Exception as e:
                logger.error(f"Error in call timeout service: {e}")

            await asyncio.sleep(self.check_interval)

    def stop(self):
        """Stop the background service"""
        self.is_running = False
        logger.info("Call timeout service stopped")

# Global instance
call_timeout_service = CallTimeoutService(check_interval=10, timeout_seconds=30)
