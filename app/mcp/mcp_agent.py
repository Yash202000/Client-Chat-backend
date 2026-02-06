import logging
import os
import json
import asyncio

from dotenv import load_dotenv

from livekit.agents import Agent, AgentSession, JobContext, WorkerOptions, cli, mcp
from livekit.plugins import silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel
from livekit.plugins import openai


logger = logging.getLogger("mcp-agent")

load_dotenv()

# LiveKit credentials from environment (matching workflow_livekit_service.py)
LIVEKIT_URL = os.getenv("LIVEKIT_URL2", os.getenv("LIVEKIT_URL", "wss://your-livekit-server.livekit.cloud"))
LIVEKIT_API_KEY = os.getenv("LIVEKIT_API_KEY2", os.getenv("LIVEKIT_API_KEY"))
LIVEKIT_API_SECRET = os.getenv("LIVEKIT_API_SECRET2", os.getenv("LIVEKIT_API_SECRET"))

# MCP Server URL (where automax_mcp.py is running)
# Using streamable-http transport endpoint (not SSE which is deprecated)
MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://127.0.0.1:8001/mcp")

# Room name prefix filter - only join rooms with this prefix
ROOM_NAME_PREFIX = "voice_workflow_"

# Store for frontend data (small data: attachment_id, lat, long)
frontend_data_store = {}


class MyAgent(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions=(
                "You are an incident creation assistant. "
                "Your role is to guide the user through a structured workflow to collect all required incident details "
                "and create an incident using tool calls. "
 
                "You must collect information step-by-step, one field at a time. "
                "Do not rush and do not skip steps. "
 
                "Two fields use hierarchical lookup systems: classification and location. "
                "Users speak natural names, but these must be converted to IDs using lookup tools. "
 
                "When classification or location is provided: "
                "call the lookup tools, search the hierarchy, select the most specific valid match, "
                "prefer leaf nodes, convert the name to its ID, and never invent IDs. "
 
                "If multiple matches exist, ask the user to clarify. "
                "If no match exists, tell the user and ask them to rephrase. "
 
                "WORKFLOW: "
                "1. Collect caller name via voice "
                "2. Collect classification via voice (use get_classifications to validate) "
                "3. Collect location via voice (use get_locations to validate) "
                "4. Summarize the information and confirm with the user "
                "5. Ask the user to submit the form on their screen with photo and location "
                "6. Wait for frontend data message (you will receive a system message when it arrives) "
                "7. Once frontend data is received, call create_incident with all the data including attachment_id, latitude, longitude "
                "8. Confirm the incident was created and end the conversation "
 
                "Speak like a calm professional dispatcher. "
                "Use short, clear sentences. "
                "Ask one question at a time. "
                "Never assume missing information. "
                "Always confirm before submission. "
            ),
        )


    async def on_enter(self):
        # When the agent is added to the session, it'll generate a reply
        self.session.generate_reply()


async def entrypoint(ctx: JobContext):
    """Main entrypoint for the MCP voice agent."""
    global frontend_data_store
    
    logger.info(f"MCP Agent connecting to room: {ctx.room.name}")
    
    # Connect to the room (audio only)
    await ctx.connect()
    
    # Wait for participant
    participant = await ctx.wait_for_participant()
    logger.info(f"Participant joined: {participant.identity}")
    
    # Create session with MCP server connection
    session = AgentSession(
        vad=ctx.proc.userdata.get("vad"),
        llm=openai.realtime.RealtimeModel(),
        turn_detection=MultilingualModel(),
        mcp_servers=[
            mcp.MCPServerHTTP(url=MCP_SERVER_URL),
        ],
    )

    # Listen for frontend data via LiveKit data channel
    @ctx.room.on("data_received")
    def on_data_received(data_packet):
        """Handle data messages from the frontend (form submissions)."""
        global frontend_data_store
        try:
            # Extract data from DataPacket object
            data = data_packet.data if hasattr(data_packet, 'data') else data_packet
            payload_str = data.decode() if isinstance(data, bytes) else str(data)
            
            # Try parsing as JSON
            try:
                payload = json.loads(payload_str)
                message_type = payload.get("type", "")
            except json.JSONDecodeError:
                message_type = payload_str
                payload = {"type": message_type}
            
            logger.info(f"Received data message: {message_type}")
            
            if message_type == "FRONTEND_DATA":
                # Store the frontend data (small: just 3 fields)
                attachment_id = payload.get("attachment_id", "")
                latitude = payload.get("latitude")
                longitude = payload.get("longitude")
                
                frontend_data_store = {
                    "attachment_id": attachment_id,
                    "latitude": latitude,
                    "longitude": longitude,
                    "received": True
                }
                
                logger.info(f"Frontend data received: attachment_id={attachment_id}, lat={latitude}, long={longitude}")
                
                # Notify the agent that frontend data is available
                # Include the data directly in the instruction so agent can use it
                asyncio.create_task(
                    session.generate_reply(
                        instructions=(
                            "FRONTEND DATA RECEIVED! "
                            f"attachment_id: '{attachment_id}' "
                            f"latitude: {latitude} "
                            f"longitude: {longitude} "
                            "You now have all the data needed. "
                            "Proceed to call create_incident with the full data including these values."
                        )
                    )
                )
                
        except Exception as e:
            logger.error(f"Error handling data message: {e}")

    await session.start(agent=MyAgent(), room=ctx.room)
    logger.info("MCP Agent session started")


def prewarm(proc):
    """Prewarm VAD model."""
    logger.info("Prewarming MCP agent...")
    proc.userdata["vad"] = silero.VAD.load()
    logger.info("Prewarm complete")


async def request_fnc(request):
    """
    Filter which rooms this agent should join.
    Only accept rooms with the voice_workflow_ prefix.
    """
    room_name = request.room.name
    should_accept = room_name.startswith(ROOM_NAME_PREFIX)
    
    if should_accept:
        logger.info(f"MCP Agent accepting job for room: {room_name}")
        await request.accept()
    else:
        logger.debug(f"MCP Agent rejecting room: {room_name} (not a voice workflow room)")
        await request.reject()


if __name__ == "__main__":
    """Run the MCP voice agent worker."""
    
    if not LIVEKIT_API_KEY or not LIVEKIT_API_SECRET:
        raise ValueError("LIVEKIT_API_KEY and LIVEKIT_API_SECRET must be set in .env")
    
    logger.info("=" * 60)
    logger.info("Starting MCP Voice Agent...")
    logger.info("=" * 60)
    logger.info(f"LiveKit URL: {LIVEKIT_URL}")
    logger.info(f"MCP Server URL: {MCP_SERVER_URL}")
    logger.info(f"Room prefix filter: {ROOM_NAME_PREFIX}*")
    logger.info("=" * 60)
    
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=prewarm,
            request_fnc=request_fnc,
            ws_url=LIVEKIT_URL,
            api_key=LIVEKIT_API_KEY,
            api_secret=LIVEKIT_API_SECRET,
        ),
    )