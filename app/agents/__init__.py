"""
LiveKit Voice Agents Module

This module provides two types of voice agents:

1. voice_agent.py - For 1:1 voice conversations with a single participant
   - Uses default LiveKit RoomIO for single participant audio
   - Ideal for customer support, personal assistants, etc.

2. conference_voice_agent.py - For multi-participant conference calls
   - Uses AudioMixer to listen to ALL participants simultaneously
   - Ideal for group meetings, webinars, panel discussions, etc.

Usage:
    # Run standalone 1:1 agent
    python app/agents/voice_agent.py dev

    # Run standalone conference agent
    python app/agents/conference_voice_agent.py dev

    # Import for programmatic use
    from app.agents import voice_agent, conference_voice_agent
"""

# Make agents available for import
from . import voice_agent
from . import conference_voice_agent

__all__ = ["voice_agent", "conference_voice_agent"]
