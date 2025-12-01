# LiveKit AI Agents Integration Guide

## Overview

This guide explains how to set up and use LiveKit AI agents for voice-only interactions in AgentConnect. The implementation allows AI agents to join LiveKit rooms and handle voice conversations autonomously.

## Architecture

```
Widget (Voice Mode)
    ↓
Creates LiveKit Room → Generates User Token
    ↓
Backend API: /livekit-agents/start-voice-session
    ↓
Spawns AI Agent Worker → Agent Joins Room
    ↓
Voice Conversation (User ↔ AI Agent)
```

## Components

### 1. Backend Services
- **livekit_agent_worker_service.py**: Manages agent lifecycle
- **voice_agent.py**: Standalone 1:1 agent worker implementation
- **conference_voice_agent.py**: Multi-participant conference agent
- **livekit_agents.py**: API endpoints for agent management

### 2. Database
- **conversation_sessions**: Extended with agent tracking fields
  - `agent_room_name`: LiveKit room name
  - `agent_worker_id`: Worker process ID
  - `agent_status`: Current status
  - `agent_started_at`: Start timestamp
  - `agent_stopped_at`: Stop timestamp

### 3. API Endpoints
- `POST /api/v1/livekit-agents/start-voice-session`: Start AI agent
- `POST /api/v1/livekit-agents/stop-voice-session`: Stop AI agent
- `GET /api/v1/livekit-agents/agent-status/{session_id}`: Get agent status
- `GET /api/v1/livekit-agents/active-agents`: List all active agents
- `POST /api/v1/livekit-agents/widget-voice-token`: Get token for widget

---

## Setup Instructions

### Step 1: Install Dependencies

The required packages are already added to `requirements.txt`. Install them:

```bash
cd backend
source venv/bin/activate
pip install -r requirements.txt
```

**Installed packages:**
- `livekit-agents==1.3.2`
- `livekit-plugins-openai==1.3.2`
- `livekit-plugins-groq==1.3.2`
- `livekit-plugins-deepgram==1.3.2`
- `livekit-plugins-silero==1.3.2`

### Step 2: Configure Environment Variables

Edit your `.env` file and add the following:

```env
# LiveKit Configuration (already exists)
LIVEKIT_URL=wss://your-livekit-server.cloud
LIVEKIT_API_KEY=your_api_key
LIVEKIT_API_SECRET=your_api_secret

# OpenAI API Key (for LLM and TTS)
OPENAI_API_KEY=sk-your-openai-api-key

# Deepgram API Key (for Speech-to-Text)
DEEPGRAM_API_KEY=your-deepgram-api-key

# Agent Configuration
AGENT_LLM_PROVIDER=openai
AGENT_LLM_MODEL=gpt-4o-mini
AGENT_STT_PROVIDER=deepgram
AGENT_TTS_PROVIDER=openai
AGENT_TTS_VOICE=alloy
AGENT_VAD_ENABLED=true
AGENT_ALLOW_INTERRUPTIONS=true
```

**Provider Options:**
- **LLM**: `openai` (gpt-4o, gpt-4o-mini) or `groq` (llama, mixtral)
- **STT**: `deepgram` or `groq`
- **TTS**: `openai` (alloy, echo, fable, onyx, nova, shimmer)

### Step 3: Run Database Migration

Apply the new database migration to add agent tracking fields:

```bash
source venv/bin/activate
alembic upgrade head
```

This will add the following columns to `conversation_sessions`:
- `agent_room_name`
- `agent_worker_id`
- `agent_status`
- `agent_started_at`
- `agent_stopped_at`

### Step 4: Start the Backend Server

```bash
source venv/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

---

## Running the Agent Worker

There are two ways to run LiveKit agents:

### Option 1: Standalone Agent Worker (Recommended for Production)

Run the agent as a separate process using the LiveKit agents CLI:

```bash
# Development mode (auto-reload)
source venv/bin/activate
python app/agents/voice_agent.py dev

# Production mode
python app/agents/voice_agent.py start
```

The agent worker will:
- Connect to your LiveKit server
- Listen for room join events
- Automatically join rooms when triggered
- Handle voice conversations using configured LLM/STT/TTS

### Option 2: API-Triggered Agents (Current Implementation)

Agents are spawned via API calls when a voice session starts. This is handled automatically by the `/start-voice-session` endpoint.

**Note:** In production, you should use Option 1 with a proper worker deployment.

---

## Agent Modes: 1:1 vs Conference

AgentConnect provides two types of voice agents for different use cases:

### 1:1 Voice Agent (`voice_agent.py`)

**Use Cases:**
- Customer support conversations
- Personal AI assistants
- One-on-one tutoring or coaching
- Private consultations

**How it works:**
- Connects to a room with `AutoSubscribe.AUDIO_ONLY`
- Uses LiveKit's default `RoomIO` for single-participant audio
- Optimized for low latency in 1:1 conversations
- The `AgentSession` automatically handles participant connection

**Run it:**
```bash
source venv/bin/activate
python app/agents/voice_agent.py dev
```

**Key Features:**
- Simple, reliable 1:1 audio handling
- Automatic participant connection management
- Lower computational overhead

---

### Conference Voice Agent (`conference_voice_agent.py`)

**Use Cases:**
- Group meetings with AI facilitation
- Multi-participant webinars or workshops
- Panel discussions with AI moderation
- Team brainstorming sessions with AI assistance

**How it works:**
- Connects to a room with `AutoSubscribe.SUBSCRIBE_ALL`
- Uses custom `ConferenceAudioMixer` to combine ALL participant audio streams
- Listens to everyone simultaneously (not just one person)
- Filters out the agent's own audio to prevent feedback loops
- Handles dynamic participant join/leave events

**Run it:**
```bash
source venv/bin/activate
python app/agents/conference_voice_agent.py dev
```

**Key Features:**
- Listens to ALL participants simultaneously
- AudioMixer combines multiple audio streams
- Dynamic participant management
- No speaker diarization (can't identify who said what)

**Important Notes:**
- The agent hears ALL participants mixed together
- Cannot distinguish between individual speakers
- Best for scenarios where the AI responds to the group as a whole
- If you need speaker identification, use parallel 1:1 agents instead

**Choosing Between Modes:**

| Feature | 1:1 Voice Agent | Conference Voice Agent |
|---------|----------------|------------------------|
| Participants | Single user | Multiple users |
| Audio Mixing | Not needed | AudioMixer combines all |
| Use Case | Support, personal assistant | Meetings, webinars |
| Latency | Lower | Slightly higher |
| Speaker ID | N/A (only one speaker) | Not supported |
| Complexity | Simple | Moderate |

---

## Usage Examples

### 1. Start a Voice Session (Widget Integration)

When the widget enters voice mode, it should call:

```javascript
const response = await fetch(`${backendUrl}/api/v1/livekit-agents/start-voice-session`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    session_id: currentSessionId,
    agent_id: agentId,
    company_id: companyId,
    llm_provider: 'openai',
    llm_model: 'gpt-4o-mini',
    stt_provider: 'deepgram',
    tts_provider: 'openai',
    voice_id: 'alloy',
    greeting_message: 'Hello! How can I help you?'
  })
});

const data = await response.json();
// data.user_token - Use this to join the LiveKit room
// data.room_name - The room name
// data.livekit_url - LiveKit server URL
```

### 2. Join the Room from Widget

```javascript
import { Room } from 'livekit-client';

const room = new Room();
await room.connect(data.livekit_url, data.user_token);

// The AI agent will already be in the room or joining
// Start speaking - the agent will respond!
```

### 3. Stop a Voice Session

```javascript
await fetch(`${backendUrl}/api/v1/livekit-agents/stop-voice-session`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    session_id: currentSessionId
  })
});
```

### 4. Check Agent Status

```javascript
const response = await fetch(`${backendUrl}/api/v1/livekit-agents/agent-status/${sessionId}`);
const status = await response.json();

console.log(status);
// {
//   session_id: "...",
//   room_name: "voice_123_456_...",
//   status: "active",
//   started_at: "2025-11-18T22:00:00",
//   worker_id: "agent_worker_123"
// }
```

---

## Widget Integration Flow

### Current Widget Voice Mode

Your widget already has a `VoiceAgentPreview` component that uses LiveKit. To integrate AI agents:

1. **Widget detects voice mode**
   ```javascript
   if (settings?.communication_mode === 'voice') {
     // Start AI agent session
     const agentSession = await startVoiceSession();

     // Connect to LiveKit room with user token
     setLiveKitToken(agentSession.user_token);
   }
   ```

2. **User joins room**
   - Widget connects to LiveKit using the token
   - AI agent is already in the room (or joins shortly after)

3. **Voice conversation**
   - User speaks → Deepgram STT transcribes
   - Text → LLM (GPT-4o-mini) processes
   - Response → OpenAI TTS synthesizes
   - Audio → Plays in user's browser

4. **Session ends**
   - User closes widget or clicks end button
   - Call `/stop-voice-session` endpoint
   - Agent leaves room

---

## Configuration Options

### LLM Providers

**OpenAI:**
```python
llm_provider="openai"
llm_model="gpt-4o-mini"  # or gpt-4o, gpt-4-turbo
```

**Groq (Fast Inference):**
```python
llm_provider="groq"
llm_model="llama-3.3-70b-versatile"  # or mixtral-8x7b-32768
```

### STT Providers

**Deepgram (Recommended):**
```python
stt_provider="deepgram"
# Low latency, high accuracy, supports streaming
```

**Groq Whisper:**
```python
stt_provider="groq"
# Fast batch transcription, good accuracy
```

### TTS Providers

**OpenAI TTS:**
```python
tts_provider="openai"
voice_id="alloy"  # Options: alloy, echo, fable, onyx, nova, shimmer
```

### System Prompt Customization

You can customize the agent's behavior via the system prompt:

```python
system_prompt = """
You are a customer support AI assistant for Acme Corp.
- Be friendly and professional
- Keep responses under 3 sentences for voice clarity
- If you don't know something, offer to connect to a human agent
- Remember: this is a voice conversation, so avoid complex explanations
"""
```

---

## Testing

### 1. Test Backend API

```bash
# Start voice session
curl -X POST http://localhost:8000/api/v1/livekit-agents/start-voice-session \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "test_123",
    "agent_id": 1,
    "company_id": 1,
    "llm_provider": "openai",
    "llm_model": "gpt-4o-mini"
  }'
```

### 2. Test 1:1 Voice Agent

```bash
# Run 1:1 agent in dev mode
source venv/bin/activate
cd backend
python app/agents/voice_agent.py dev
```

Open another terminal and create a test room using the LiveKit CLI or dashboard.

### 3. Test Conference Voice Agent

```bash
# Run conference agent in dev mode
source venv/bin/activate
cd backend
python app/agents/conference_voice_agent.py dev
```

**Test with multiple participants:**
1. Create a room in LiveKit dashboard
2. Join the room with 2+ browser tabs (different users)
3. Speak from different tabs - the agent should hear everyone
4. Verify the agent responds to the group conversation

### 4. Test Widget Integration

1. Build the widget with voice mode enabled
2. Set `communication_mode: 'voice'` in widget settings
3. Open the widget in a browser
4. Start speaking - the AI agent should respond

---

## Troubleshooting

### Issue: Agent Not Joining Room

**Check:**
1. LiveKit credentials are correct in `.env`
2. Agent worker is running (`python app/agents/voice_agent.py dev`)
3. Room name matches between user token and agent config
4. Firewall allows WebRTC traffic

**Solution:**
```bash
# Check agent logs
python app/agents/voice_agent.py dev
# Look for "Agent connecting to room" message
```

### Issue: No Audio from Agent

**Check:**
1. OpenAI API key is valid
2. TTS provider is configured correctly
3. Browser has microphone permissions
4. Audio output is not muted

**Solution:**
Test TTS separately:
```python
from livekit.plugins import openai
tts = openai.TTS(voice="alloy")
await tts.synthesize("Hello world")
```

### Issue: Agent Not Understanding Speech

**Check:**
1. Deepgram API key is valid
2. Microphone is working
3. VAD (Voice Activity Detection) is enabled
4. Language is set correctly

**Solution:**
Check STT logs in agent worker output.

---

## Deployment

### Production Checklist

- [ ] Set up proper API keys (OpenAI, Deepgram)
- [ ] Configure LiveKit server in production
- [ ] Run agent workers as systemd services or Docker containers
- [ ] Set up monitoring for agent health
- [ ] Implement graceful shutdown for agents
- [ ] Add rate limiting for agent creation
- [ ] Set up logging and alerting

### Systemd Service (Linux)

**For 1:1 Voice Agent:**

Create `/etc/systemd/system/livekit-agent.service`:

```ini
[Unit]
Description=LiveKit AI Agent Worker (1:1 Mode)
After=network.target

[Service]
Type=simple
User=agentconnect
WorkingDirectory=/path/to/backend
Environment="PATH=/path/to/venv/bin"
ExecStart=/path/to/venv/bin/python app/agents/voice_agent.py start
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

**For Conference Voice Agent:**

Create `/etc/systemd/system/livekit-conference-agent.service`:

```ini
[Unit]
Description=LiveKit Conference AI Agent Worker (Multi-participant Mode)
After=network.target

[Service]
Type=simple
User=agentconnect
WorkingDirectory=/path/to/backend
Environment="PATH=/path/to/venv/bin"
ExecStart=/path/to/venv/bin/python app/agents/conference_voice_agent.py start
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

You can run both agents simultaneously for different use cases.

Enable and start:
```bash
# For 1:1 agent
sudo systemctl enable livekit-agent
sudo systemctl start livekit-agent
sudo systemctl status livekit-agent

# For conference agent (optional)
sudo systemctl enable livekit-conference-agent
sudo systemctl start livekit-conference-agent
sudo systemctl status livekit-conference-agent
```

### Docker Deployment

**For 1:1 Voice Agent:**

Create `Dockerfile.voice-agent`:

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ ./app/
CMD ["python", "app/agents/voice_agent.py", "start"]
```

Build and run:
```bash
docker build -f Dockerfile.voice-agent -t livekit-voice-agent .
docker run -d --env-file .env livekit-voice-agent
```

**For Conference Voice Agent:**

Create `Dockerfile.conference-agent`:

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ ./app/
CMD ["python", "app/agents/conference_voice_agent.py", "start"]
```

Build and run:
```bash
docker build -f Dockerfile.conference-agent -t livekit-conference-agent .
docker run -d --env-file .env livekit-conference-agent
```

**Run both agents together:**
```bash
docker-compose up -d
```

Example `docker-compose.yml`:
```yaml
version: '3.8'
services:
  voice-agent:
    build:
      context: .
      dockerfile: Dockerfile.voice-agent
    env_file: .env
    restart: always

  conference-agent:
    build:
      context: .
      dockerfile: Dockerfile.conference-agent
    env_file: .env
    restart: always
```

---

## Next Steps

1. **Test the implementation** with your widget
2. **Customize the system prompt** for your use case
3. **Monitor agent performance** and adjust LLM/STT/TTS settings
4. **Set up production deployment** using systemd or Docker
5. **Add analytics** to track agent usage and success rates

---

## API Reference

### POST /api/v1/livekit-agents/start-voice-session

**Request:**
```json
{
  "session_id": "string",
  "agent_id": "integer",
  "company_id": "integer",
  "llm_provider": "openai",
  "llm_model": "gpt-4o-mini",
  "stt_provider": "deepgram",
  "tts_provider": "openai",
  "voice_id": "alloy",
  "system_prompt": "optional custom prompt",
  "greeting_message": "Hello! How can I help?"
}
```

**Response:**
```json
{
  "success": true,
  "session_id": "string",
  "room_name": "voice_1_2_session_timestamp",
  "livekit_url": "wss://your-server.cloud",
  "user_token": "jwt_token_for_user",
  "agent_token": "jwt_token_for_agent",
  "status": "starting",
  "message": "Voice session initiated..."
}
```

---

## Support

For issues or questions:
1. Check the logs: `python app/agents/voice_agent.py dev`
2. Verify environment variables are set correctly
3. Test individual components (LLM, STT, TTS) separately
4. Check LiveKit dashboard for room status

---

## License

Copyright © 2025 AgentConnect. All rights reserved.
