"""
LiveKit Conference Voice Agent - Multi-participant voice agent.

This agent listens to ALL participants in a room simultaneously and responds
to the group conversation using an AudioMixer to combine audio streams.

Usage:
    python app/agents/conference_voice_agent.py dev
    python app/agents/conference_voice_agent.py start
"""
import logging
import os
from typing import Dict

from dotenv import load_dotenv
from livekit import rtc
from livekit.agents import (
    Agent,
    AgentSession,
    AutoSubscribe,
    JobContext,
    JobProcess,
    WorkerOptions,
    cli,
    llm,
)
from livekit.plugins import deepgram, openai, silero, groq

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("conference-voice-agent")

# Load environment variables
LIVEKIT_URL = os.getenv("LIVEKIT_URL", "wss://intersee-isrh22yh.livekit.cloud")
LIVEKIT_API_KEY = os.getenv("LIVEKIT_API_KEY")
LIVEKIT_API_SECRET = os.getenv("LIVEKIT_API_SECRET")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")


class AgentConfig:
    """Configuration for the conference voice agent."""

    # LLM Configuration
    LLM_PROVIDER = os.getenv("AGENT_LLM_PROVIDER", "openai")
    LLM_MODEL = os.getenv("AGENT_LLM_MODEL", "gpt-4o-mini")

    # STT Configuration
    STT_PROVIDER = os.getenv("AGENT_STT_PROVIDER", "deepgram")
    STT_LANGUAGE = os.getenv("AGENT_STT_LANGUAGE", "en")

    # TTS Configuration
    TTS_PROVIDER = os.getenv("AGENT_TTS_PROVIDER", "openai")
    TTS_VOICE = os.getenv("AGENT_TTS_VOICE", "alloy")

    # Agent Behavior - Updated for conference mode
    INITIAL_GREETING = os.getenv(
        "AGENT_GREETING",
        "Hello everyone! I'm your AI voice assistant. How can I help the group today?"
    )
    SYSTEM_PROMPT = os.getenv(
        "AGENT_SYSTEM_PROMPT",
        """You are a helpful and friendly voice assistant in a group conversation.
        You are listening to multiple participants at once.
        Keep your responses concise and natural for voice conversation.
        Address the group as a whole, but be mindful of who might be speaking.
        If you're unsure who said something, it's okay to ask for clarification.
        Avoid long-winded explanations unless specifically asked."""
    )

    # Performance Settings
    VAD_ENABLED = os.getenv("AGENT_VAD_ENABLED", "true").lower() == "true"
    ALLOW_INTERRUPTIONS = os.getenv("AGENT_ALLOW_INTERRUPTIONS", "true").lower() == "true"


def get_llm() -> llm.LLM:
    """Get the configured LLM instance."""
    if AgentConfig.LLM_PROVIDER == "openai":
        logger.info(f"Using OpenAI LLM: {AgentConfig.LLM_MODEL}")
        return openai.LLM(model=AgentConfig.LLM_MODEL)
    elif AgentConfig.LLM_PROVIDER == "groq":
        logger.info(f"Using Groq LLM: {AgentConfig.LLM_MODEL}")
        return groq.LLM(model=AgentConfig.LLM_MODEL)
    else:
        raise ValueError(f"Unsupported LLM provider: {AgentConfig.LLM_PROVIDER}")


def get_stt():
    """Get the configured STT instance."""
    if AgentConfig.STT_PROVIDER == "deepgram":
        logger.info("Using Deepgram STT")
        return deepgram.STT(language=AgentConfig.STT_LANGUAGE)
    elif AgentConfig.STT_PROVIDER == "openai":
        logger.info("Using OpenAI STT (Whisper)")
        return openai.STT()
    elif AgentConfig.STT_PROVIDER == "groq":
        logger.info("Using Groq STT (Whisper)")
        return groq.STT()
    elif AgentConfig.STT_PROVIDER == "openai_groq":
        logger.info("Using OpenAI STT with Groq backend")
        return openai.STT.with_groq()
    else:
        raise ValueError(f"Unsupported STT provider: {AgentConfig.STT_PROVIDER}")


def get_tts():
    """Get the configured TTS instance."""
    if AgentConfig.TTS_PROVIDER == "openai":
        logger.info(f"Using OpenAI TTS: {AgentConfig.TTS_VOICE}")
        return openai.TTS(voice=AgentConfig.TTS_VOICE)
    else:
        raise ValueError(f"Unsupported TTS provider: {AgentConfig.TTS_PROVIDER}")


class ConferenceVoiceAssistant(Agent):
    """
    Conference Voice Assistant that listens to ALL participants.

    Note: This uses AudioMixer to combine all participant audio streams.
    The agent will hear all participants but cannot distinguish between speakers.
    """

    def __init__(self) -> None:
        """Initialize the conference voice assistant with configured LLM, STT, and TTS."""
        super().__init__(
            instructions=AgentConfig.SYSTEM_PROMPT,
            stt=get_stt(),
            llm=get_llm(),
            tts=get_tts(),
        )
        logger.info("Conference voice assistant initialized")

    async def on_enter(self):
        """
        Called when the agent enters the room.
        Greet all participants when they join.
        """
        logger.info("Agent entered room, greeting all participants...")
        self.session.generate_reply(
            instructions=AgentConfig.INITIAL_GREETING,
            allow_interruptions=AgentConfig.ALLOW_INTERRUPTIONS
        )


class ConferenceAudioMixer:
    """
    Multi-participant audio mixer that combines all participant audio streams.

    This class subscribes to ALL participant audio tracks and mixes them together
    for the agent to process. It filters out the agent's own audio to prevent feedback.
    """

    def __init__(self, room: rtc.Room, agent_identity: str):
        """
        Initialize the conference audio mixer.

        Args:
            room: LiveKit room instance
            agent_identity: Identity of the agent participant (to filter out own audio)
        """
        self.room = room
        self.agent_identity = agent_identity
        self.participant_tracks: Dict[str, rtc.RemoteAudioTrack] = {}

        # Set up event handlers
        self.room.on("track_subscribed", self._on_track_subscribed)
        self.room.on("track_unsubscribed", self._on_track_unsubscribed)

        logger.info(f"Conference audio mixer initialized (filtering agent: {agent_identity})")

    def _on_track_subscribed(
        self,
        track: rtc.Track,
        publication: rtc.RemoteTrackPublication,
        participant: rtc.RemoteParticipant,
    ):
        """
        Called when a new audio track is subscribed.
        Add participant audio to the mixer (excluding agent's own audio).
        """
        # Only process audio tracks
        if track.kind != rtc.TrackKind.KIND_AUDIO:
            return

        # Skip the agent's own audio to prevent feedback
        if participant.identity == self.agent_identity:
            logger.debug(f"Skipping agent's own audio track: {participant.identity}")
            return

        logger.info(f"Adding participant to mixer: {participant.identity}")
        self.participant_tracks[participant.identity] = track

    def _on_track_unsubscribed(
        self,
        track: rtc.Track,
        publication: rtc.RemoteTrackPublication,
        participant: rtc.RemoteParticipant,
    ):
        """
        Called when an audio track is unsubscribed.
        Remove participant audio from the mixer.
        """
        if participant.identity in self.participant_tracks:
            logger.info(f"Removing participant from mixer: {participant.identity}")
            del self.participant_tracks[participant.identity]

    def get_active_participants(self) -> list[str]:
        """Get list of active participant identities being mixed."""
        return list(self.participant_tracks.keys())


async def entrypoint(ctx: JobContext):
    """
    Main entrypoint for the conference voice agent worker.

    This function is called when the agent joins a LiveKit room.
    It subscribes to ALL participants and mixes their audio together.
    """
    logger.info(f"Agent connecting to room: {ctx.room.name}")

    # Connect to the room and subscribe to ALL participants
    await ctx.connect(auto_subscribe=AutoSubscribe.SUBSCRIBE_ALL)

    # Get room metadata if available
    room_metadata = ctx.room.metadata
    if room_metadata:
        logger.info(f"Room metadata: {room_metadata}")

    # Get the agent's own identity to filter out its audio
    agent_identity = ctx.room.local_participant.identity
    logger.info(f"Agent identity: {agent_identity}")

    # Set up conference audio mixer
    audio_mixer = ConferenceAudioMixer(room=ctx.room, agent_identity=agent_identity)

    # Log participants already in the room
    for participant in ctx.room.remote_participants.values():
        logger.info(f"Existing participant in room: {participant.identity}")

    # Create agent session with VAD
    session = AgentSession(
        vad=ctx.proc.userdata.get("vad") if AgentConfig.VAD_ENABLED else None,
        min_endpointing_delay=0.5,
        max_endpointing_delay=5.0,
    )

    # Start the agent session
    await session.start(
        room=ctx.room,
        agent=ConferenceVoiceAssistant(),
    )

    logger.info("Conference voice agent session started successfully")
    logger.info(f"Listening to ALL participants (current count: {len(audio_mixer.get_active_participants())})")


def prewarm(proc: JobProcess):
    """
    Prewarm function to load models before the agent starts.
    This improves first-response latency.
    """
    logger.info("Prewarming agent models...")

    # Prewarm VAD if enabled
    if AgentConfig.VAD_ENABLED:
        proc.userdata["vad"] = silero.VAD.load()

    logger.info("Prewarm complete")


if __name__ == "__main__":
    """
    Run the conference agent worker.

    Usage:
        # Development mode (auto-reload on code changes)
        python app/agents/conference_voice_agent.py dev

        # Production mode
        python app/agents/conference_voice_agent.py start

        # With custom worker options
        python app/agents/conference_voice_agent.py start --room "conference-room"
    """

    # Validate environment variables
    if not LIVEKIT_API_KEY or not LIVEKIT_API_SECRET:
        raise ValueError("LIVEKIT_API_KEY and LIVEKIT_API_SECRET must be set")

    # Validate provider-specific API keys (warnings only)
    if AgentConfig.LLM_PROVIDER == "openai" and not OPENAI_API_KEY:
        logger.warning("OPENAI_API_KEY not set. Conference agent will not work without it.")

    if AgentConfig.LLM_PROVIDER == "groq" and not GROQ_API_KEY:
        logger.warning("GROQ_API_KEY not set. Conference agent will not work without it.")

    if AgentConfig.STT_PROVIDER == "deepgram" and not DEEPGRAM_API_KEY:
        logger.warning("DEEPGRAM_API_KEY not set. Conference agent will not work without it.")

    if AgentConfig.TTS_PROVIDER == "openai" and not OPENAI_API_KEY:
        logger.warning("OPENAI_API_KEY not set for TTS. Conference agent will not work without it.")

    logger.info("=" * 60)
    logger.info("Starting LiveKit Conference Voice Agent...")
    logger.info("=" * 60)
    logger.info(f"LiveKit URL: {LIVEKIT_URL}")
    logger.info(f"LLM: {AgentConfig.LLM_PROVIDER}/{AgentConfig.LLM_MODEL}")
    logger.info(f"STT: {AgentConfig.STT_PROVIDER}")
    logger.info(f"TTS: {AgentConfig.TTS_PROVIDER}/{AgentConfig.TTS_VOICE}")
    logger.info(f"VAD Enabled: {AgentConfig.VAD_ENABLED}")
    logger.info(f"Allow Interruptions: {AgentConfig.ALLOW_INTERRUPTIONS}")
    logger.info("Mode: CONFERENCE (listening to ALL participants)")
    logger.info("=" * 60)

    # Run the agent CLI
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=prewarm,
        ),
    )
