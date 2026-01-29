"""
Workflow Voice Agent - LiveKit agent for executing voice workflows.

This agent:
- Reads workflow JSON from room metadata on connection
- Uses OpenAI LLM + Deepgram STT + OpenAI TTS
- Implements BackendBridge tool for calling server endpoints
- Listens for data_received events to resume after form submission
- Generates system prompt dynamically from workflow context

Run with:
    python app/agents/workflow_voice_agent.py dev    # Development mode
    python app/agents/workflow_voice_agent.py start  # Production mode
"""
import asyncio
import json
import logging
import os
from typing import Annotated

import httpx
from dotenv import load_dotenv
from livekit.agents import (
    Agent,
    AgentSession,
    AutoSubscribe,
    JobContext,
    JobProcess,
    RoomInputOptions,
    RoomOutputOptions,
    WorkerOptions,
    cli,
    llm,
)
from livekit.plugins import openai, silero

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("workflow-voice-agent")

# Environment configuration - use LIVEKIT_*2 to match workflow_livekit_service.py
LIVEKIT_URL = os.getenv("LIVEKIT_URL2", os.getenv("LIVEKIT_URL", "wss://your-livekit-server.livekit.cloud"))
LIVEKIT_API_KEY = os.getenv("LIVEKIT_API_KEY2", os.getenv("LIVEKIT_API_KEY"))
LIVEKIT_API_SECRET = os.getenv("LIVEKIT_API_SECRET2", os.getenv("LIVEKIT_API_SECRET"))
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Room name prefix for this agent
ROOM_NAME_PREFIX = "voice_workflow_"

# Agent configuration
LLM_MODEL = os.getenv("AGENT_LLM_MODEL", "gpt-4o-mini")
TTS_VOICE = os.getenv("AGENT_TTS_VOICE", "alloy")
STT_LANGUAGE = os.getenv("AGENT_STT_LANGUAGE", "en")
VAD_ENABLED = os.getenv("AGENT_VAD_ENABLED", "true").lower() == "true"


class WorkflowContext:
    """Holds workflow context parsed from room metadata."""
    
    def __init__(self, metadata: dict):
        self.session_id = metadata.get("session_id", "unknown")
        self.workflow = metadata.get("workflow", {})
        self.backend_url = metadata.get("backend_url", "http://localhost:8000")
        self.greeting_message = metadata.get("greeting_message")
        self.agent_id = metadata.get("agent_id")
        self.company_id = metadata.get("company_id")
        
        # DEBUG: Log what workflow data we received
        logger.info(f"[WORKFLOW CONTEXT] workflow type: {type(self.workflow)}")
        logger.info(f"[WORKFLOW CONTEXT] workflow keys: {list(self.workflow.keys()) if isinstance(self.workflow, dict) else 'NOT A DICT'}")
        
        # If workflow is a string, try to parse it
        if isinstance(self.workflow, str):
            try:
                import json
                self.workflow = json.loads(self.workflow)
                logger.info(f"[WORKFLOW CONTEXT] Parsed workflow from string, keys: {list(self.workflow.keys())}")
            except:
                logger.error(f"[WORKFLOW CONTEXT] Failed to parse workflow string")
                self.workflow = {}
        
        # Extract workflow details
        self.workflow_name = self.workflow.get("name", "Workflow")
        self.workflow_description = self.workflow.get("description", "")
        
        logger.info(f"[WORKFLOW CONTEXT] Workflow name: {self.workflow_name}")
        
        # Extract services from first prompt node's options
        self.services = self._extract_services()
        
        # Extract all workflow steps that collect user input
        self.input_steps = self._extract_input_steps()
        
    def _get_nodes(self) -> list:
        """Get nodes from workflow, handling different JSON structures."""
        # Try visual_steps.nodes first (940 workflow format)
        visual_steps = self.workflow.get("visual_steps", {})
        
        # visual_steps might be a string
        if isinstance(visual_steps, str):
            try:
                import json
                visual_steps = json.loads(visual_steps)
                logger.info(f"[WORKFLOW CONTEXT] Parsed visual_steps from string")
            except:
                visual_steps = {}
        
        nodes = visual_steps.get("nodes", []) if isinstance(visual_steps, dict) else []
        logger.info(f"[WORKFLOW CONTEXT] visual_steps.nodes count: {len(nodes)}")
        
        if nodes:
            return nodes
        
        # Fall back to root-level nodes
        root_nodes = self.workflow.get("nodes", [])
        logger.info(f"[WORKFLOW CONTEXT] root nodes count: {len(root_nodes)}")
        return root_nodes
    
    def _extract_services(self) -> list:
        """Extract service options from the first prompt node (main menu)."""
        nodes = self._get_nodes()
        
        for node in nodes:
            if node.get("type") == "prompt":
                params = node.get("data", {}).get("params", {})
                options = params.get("options", "")
                if options:
                    return [opt.strip() for opt in options.split(",")]
        return []
    
    def _extract_input_steps(self) -> list:
        """Extract all steps that require user input with their variable names."""
        nodes = self._get_nodes()
        steps = []
        
        for node in nodes:
            node_type = node.get("type", "")
            node_id = node.get("id", "")
            data = node.get("data", {})
            params = data.get("params", {})
            
            if node_type == "prompt":
                steps.append({
                    "node_id": node_id,
                    "type": "prompt",
                    "variable_name": params.get("save_to_variable", ""),
                    "prompt_text": params.get("prompt_text", ""),
                    "options": params.get("options", ""),
                    "label": data.get("label", "")
                })
            elif node_type == "listen":
                expected_type = params.get("expected_input_type", "text")
                steps.append({
                    "node_id": node_id,
                    "type": "listen",
                    "variable_name": params.get("save_to_variable", ""),
                    "input_type": expected_type,  # text, attachment, location
                    "requires_form": expected_type in ["attachment", "location"],
                    "label": data.get("label", "")
                })
            elif node_type == "code":
                steps.append({
                    "node_id": node_id,
                    "type": "code",
                    "label": data.get("label", ""),
                    "return_variables": data.get("return_variables", []),
                    "arguments": data.get("arguments", [])
                })
        
        return steps
    
    def get_variables_to_collect(self) -> list:
        """Get list of variable names that need to be collected from user."""
        variables = []
        for step in self.input_steps:
            if step.get("type") in ["prompt", "listen"] and step.get("variable_name"):
                variables.append({
                    "name": step["variable_name"],
                    "type": step.get("input_type", "text"),
                    "requires_form": step.get("requires_form", False)
                })
        return variables
    def _build_workflow_graph(self) -> str:
        """Build a readable workflow graph using BFS traversal."""
        from collections import defaultdict, deque
        
        nodes = self._get_nodes()
        edges = self._get_edges()
        
        if not nodes:
            return "No workflow steps defined."
        
        # Build node registry
        node_type_map = {}
        node_label_map = {}
        
        for n in nodes:
            nid = n.get("id")
            node_type_map[nid] = n.get("type", "unknown")
            data = n.get("data", {})
            params = data.get("params", {})
            
            # Get best label for node
            label = (
                data.get("label") or 
                data.get("output_value", "")[:50] or
                params.get("prompt_text", "")[:50] or
                n.get("type", "unknown")
            )
            node_label_map[nid] = label
        
        # Build adjacency list
        adjacency = defaultdict(list)
        for e in edges:
            src = e.get("source")
            tgt = e.get("target")
            handle = e.get("sourceHandle", "output")
            adjacency[src].append((handle, tgt))
        
        # Find start node
        start_node = None
        for nid, ntype in node_type_map.items():
            if ntype == "start":
                start_node = nid
                break
        
        if not start_node:
            # Use first node if no start
            start_node = nodes[0].get("id") if nodes else None
        
        # BFS traversal order
        visited = set()
        queue = deque([start_node]) if start_node else deque()
        bfs_order = []
        
        while queue:
            n = queue.popleft()
            if n in visited or n is None:
                continue
            visited.add(n)
            bfs_order.append(n)
            for _, child in adjacency.get(n, []):
                if child not in visited:
                    queue.append(child)
        
        # Build output text
        lines = []
        lines.append("=== EXECUTION ORDER ===")
        for i, nid in enumerate(bfs_order[:30]):  # Limit to 30 nodes
            ntype = node_type_map.get(nid, "unknown")
            label = node_label_map.get(nid, "")[:40]
            
            # Format by type with emoji
            if ntype == "start":
                lines.append(f"{i+1}. � START")
            elif ntype == "response":
                lines.append(f"{i+1}. � SAY: \"{label}\"")
            elif ntype == "prompt":
                lines.append(f"{i+1}. ❓ ASK: \"{label}\"")
            elif ntype == "listen":
                lines.append(f"{i+1}. � LISTEN for input")
            elif ntype == "condition":
                lines.append(f"{i+1}. 🔀 CHECK: {label}")
            elif ntype == "code":
                lines.append(f"{i+1}. ⚙️ EXECUTE: {label}")
            elif ntype == "tool":
                lines.append(f"{i+1}. 🔧 TOOL: {label}")
            else:
                lines.append(f"{i+1}. 📌 {ntype.upper()}: {label}")
        
        # Add edge descriptions (transitions)
        lines.append("\n=== TRANSITIONS ===")
        edge_count = 0
        for src, neighbors in adjacency.items():
            if edge_count >= 20:  # Limit edges
                lines.append("... (more transitions)")
                break
            for handle, tgt in neighbors:
                src_label = node_label_map.get(src, src)[:25]
                tgt_label = node_label_map.get(tgt, tgt)[:25]
                lines.append(f"- {src_label} --[{handle}]--> {tgt_label}")
                edge_count += 1
        
        return "\n".join(lines)
    
    def _get_edges(self) -> list:
        """Get edges from workflow, handling different JSON structures."""
        edges = self.workflow.get("visual_steps", {}).get("edges", [])
        if edges:
            return edges
        return self.workflow.get("edges", [])
        
    def generate_system_prompt(self) -> str:
        """Generate a system prompt based on the workflow."""
        # Build services text
        services_text = ""
        if self.services:
            services_text = f"\n\nYou can help with: {', '.join(self.services)}"
        
        # Build workflow graph
        workflow_graph = self._build_workflow_graph()
        
        # Build variables list for structured extraction
        variables = self.get_variables_to_collect()
        var_list = "\n".join([f"  - ${v['name']}: {'📎 (requires form)' if v['requires_form'] else '🎤 (voice)'}" for v in variables])
        
        base_prompt = f"""You are a helpful voice assistant executing the "{self.workflow_name}" workflow.{services_text}

CONVERSATION FLOW (follow this path):
{workflow_graph}

VARIABLES TO COLLECT:
{var_list}

YOUR JOB:
1. Follow the CONVERSATION FLOW above step by step
2. After user answers each question, call store_collected_data with the variable name and value
3. For 📎 FILE or 📍 LOCATION steps: call request_form_input, then keep asking user to fill the form
4. For ⚙️ EXECUTE steps: say "Let me process that" and call execute_workflow_step
5. Move to the next step after each action

TOOL USAGE:
- store_collected_data({{"variable_name": "value"}}) - ALWAYS call after user answers
- request_form_input("attachment", "var_name") - When file/location needed
- execute_workflow_step("step_id") - For processing steps

RULES:
- Follow the flow EXACTLY as shown above
- Keep responses SHORT (this is voice)
- Say what the 💬 SAY nodes tell you to say
- Ask what the ❓ ASK nodes tell you to ask
"""
        
        return base_prompt


# Global workflow context holder for function tools
_workflow_ctx: WorkflowContext = None
_http_client: httpx.AsyncClient = None


async def get_http_client() -> httpx.AsyncClient:
    """Get or create HTTP client."""
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(timeout=30.0)
    return _http_client


@llm.function_tool()
async def request_server_logic(
    action: str,
    data: str = "{}"
) -> str:
    """
    Call the backend server to execute workflow actions.
    
    Args:
        action: Action to execute - 'request_files' for file upload, 
                'update_data' to save data, 'create_incident' to create record,
                or 'request_handoff' to transfer to human agent
        data: JSON string of data collected from the conversation
    
    Returns:
        Response from the server
    """
    global _workflow_ctx
    
    if _workflow_ctx is None:
        return "SERVER_ERROR: Workflow context not initialized"
    
    logger.info(f"Calling backend: action={action}, data={data}")
    
    try:
        client = await get_http_client()
        response = await client.post(
            f"{_workflow_ctx.backend_url}/api/v1/voice-workflow/step",
            json={
                "session_id": _workflow_ctx.session_id,
                "action": action,
                "data": data
            }
        )
        result = response.json()
        
        logger.info(f"Backend response: {result}")
        
        # Handle different response statuses
        if result.get("status") == "waiting_for_input":
            url = result.get("url", "")
            return f"SENT_FORM: {url}. Tell the user: I've sent you a link to upload the required files. Please check it and let me know when you're done."
        
        elif result.get("status") == "success":
            return f"SERVER_SUCCESS: {result.get('message', 'Action completed successfully')}"
        
        elif result.get("status") == "error":
            return f"SERVER_ERROR: {result.get('message', 'An error occurred')}"
        
        else:
            return f"SERVER_RESPONSE: {result.get('message', 'Action processed')}"
            
    except Exception as e:
        logger.error(f"Backend call failed: {e}")
        return f"SERVER_ERROR: Failed to communicate with server - {str(e)}"


@llm.function_tool()
async def store_collected_data(data: str) -> str:
    """
    Store data collected from the user during conversation.
    Call this after the user answers each question with the correct variable name.
    
    Args:
        data: JSON string mapping variable name to value, e.g. '{"user_name": "John"}'
              The variable name should match the workflow's save_to_variable field.
    
    Returns:
        Confirmation that data was stored
    """
    global _workflow_ctx
    
    if _workflow_ctx is None:
        return "ERROR: Session not initialized"
    
    logger.info(f"Storing collected data: {data}")
    
    try:
        client = await get_http_client()
        response = await client.post(
            f"{_workflow_ctx.backend_url}/api/v1/voice-workflow/step",
            json={
                "session_id": _workflow_ctx.session_id,
                "action": "store_data",
                "data": data
            }
        )
        result = response.json()
        logger.info(f"Store data response: {result}")
        
        if result.get("status") == "success":
            return "DATA_STORED: Successfully saved. Continue with the next question."
        else:
            return f"DATA_ERROR: {result.get('message', 'Failed to store data')}"
            
    except Exception as e:
        logger.error(f"Store data failed: {e}")
        return f"ERROR: {str(e)}"


@llm.function_tool()
async def request_form_input(field_type: str, variable_name: str) -> str:
    """
    Request form input for data that cannot be collected via voice (files, images, location).
    After calling this, tell the user to check the chat for a form link.
    
    Args:
        field_type: Type of input needed - 'attachment' for files/images, 'location' for GPS
        variable_name: The variable name to store the result (matches workflow save_to_variable)
    
    Returns:
        Form URL if successful, or status message
    """
    global _workflow_ctx
    
    if _workflow_ctx is None:
        return "ERROR: Session not initialized"
    
    logger.info(f"Requesting form input: type={field_type}, variable={variable_name}")
    
    try:
        client = await get_http_client()
        response = await client.post(
            f"{_workflow_ctx.backend_url}/api/v1/voice-workflow/step",
            json={
                "session_id": _workflow_ctx.session_id,
                "action": "request_form",
                "data": json.dumps({
                    "field_type": field_type,
                    "variable_name": variable_name
                })
            }
        )
        result = response.json()
        logger.info(f"Request form response: {result}")
        
        if result.get("status") == "waiting_for_input":
            url = result.get("url", "")
            return f"FORM_SENT: A form has been sent to the chat. Tell the user: 'I've sent a form to your chat for uploading {field_type}. Please fill it out and let me know when done.'"
        else:
            return f"FORM_ERROR: {result.get('message', 'Failed to send form')}"
            
    except Exception as e:
        logger.error(f"Request form failed: {e}")
        return f"ERROR: {str(e)}"


@llm.function_tool()
async def execute_workflow_step(step_id: str, step_type: str = "code") -> str:
    """
    Execute a workflow processing step on the server (code execution, HTTP requests, etc).
    Say "Let me process that for you" before calling this.
    
    Args:
        step_id: The node ID of the step to execute (e.g. "code-1766053887866")
        step_type: Type of step - "code", "http_request", or "tool"
    
    Returns:
        Result of the execution
    """
    global _workflow_ctx
    
    if _workflow_ctx is None:
        return "ERROR: Session not initialized"
    
    logger.info(f"Executing workflow step: id={step_id}, type={step_type}")
    
    try:
        client = await get_http_client()
        response = await client.post(
            f"{_workflow_ctx.backend_url}/api/v1/voice-workflow/step",
            json={
                "session_id": _workflow_ctx.session_id,
                "action": "execute_step",
                "data": json.dumps({
                    "step_id": step_id,
                    "step_type": step_type
                })
            }
        )
        result = response.json()
        logger.info(f"Execute step response: {result}")
        
        if result.get("status") == "success":
            output = result.get("output", {})
            return f"STEP_COMPLETED: Processing done. Result: {json.dumps(output) if output else 'Success'}. Continue to the next step."
        elif result.get("status") == "processing":
            return "STEP_PROCESSING: Still processing. Wait a moment and check again."
        else:
            return f"STEP_ERROR: {result.get('message', 'Step execution failed')}"
            
    except Exception as e:
        logger.error(f"Execute step failed: {e}")
        return f"ERROR: {str(e)}"


class WorkflowVoiceAssistant(Agent):
    """Voice assistant that executes workflows."""
    
    def __init__(self, ctx: WorkflowContext):
        self.workflow_ctx = ctx
        
        super().__init__(
            instructions=ctx.generate_system_prompt(),
            stt=openai.STT(),  # Uses OpenAI Whisper
            llm=openai.LLM(model=LLM_MODEL),
            tts=openai.TTS(voice=TTS_VOICE),
        )
        logger.info(f"Workflow voice assistant initialized for: {ctx.workflow_name}")
    
    # Note: on_enter removed - greeting is handled in entrypoint after session.start()


# Global variable to hold the agent session for data message handling
_current_session: AgentSession = None


async def entrypoint(ctx: JobContext):
    """Main entrypoint for the workflow voice agent worker."""
    global _current_session, _workflow_ctx
    
    try:
        logger.info(f"Workflow agent connecting to room: {ctx.room.name}")
        
        # Connect to the room (audio only)
        await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
        logger.info("Connected to room successfully")
        
        # Extract session_id from room name (format: voice_workflow_{session_id})
        room_name = ctx.room.name
        session_id = room_name.replace("voice_workflow_", "") if room_name.startswith("voice_workflow_") else None
        logger.info(f"[WORKFLOW FETCH] Room: {room_name}, Session ID: {session_id}")
        
        # ALWAYS fetch workflow from backend - don't rely on room metadata
        metadata = {"session_id": session_id}
        workflow_fetched = False
        
        if session_id:
            backend_url = os.getenv("BACKEND_URL", "http://localhost:8000")
            logger.info(f"[WORKFLOW FETCH] Fetching from: {backend_url}/api/v1/voice-workflow/session/{session_id}")
            
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.get(f"{backend_url}/api/v1/voice-workflow/session/{session_id}")
                    logger.info(f"[WORKFLOW FETCH] Response status: {response.status_code}")
                    
                    if response.status_code == 200:
                        session_data = response.json()
                        logger.info(f"[WORKFLOW FETCH] Session data keys: {list(session_data.keys())}")
                        
                        if session_data.get("workflow_json"):
                            metadata["workflow"] = session_data["workflow_json"]
                            metadata["backend_url"] = backend_url
                            workflow_fetched = True
                            wf_name = session_data["workflow_json"].get("name", "Unknown")
                            wf_nodes = len(session_data["workflow_json"].get("nodes", []))
                            vs_nodes = len(session_data["workflow_json"].get("visual_steps", {}).get("nodes", []))
                            logger.info(f"[WORKFLOW FETCH] SUCCESS! Workflow: {wf_name}, root nodes: {wf_nodes}, visual_steps nodes: {vs_nodes}")
                    else:
                        logger.error(f"[WORKFLOW FETCH] Failed: {response.status_code} - {response.text[:200]}")
            except Exception as e:
                logger.error(f"[WORKFLOW FETCH] Exception: {e}")
        
        if not workflow_fetched:
            logger.error("[WORKFLOW FETCH] FAILED - No workflow data available!")
        
        workflow_ctx = WorkflowContext(metadata)
        _workflow_ctx = workflow_ctx  # Set global context for function tools
        
        # Detailed logging for debugging
        logger.info(f"[AGENT DEBUG] Session ID: {workflow_ctx.session_id}")
        logger.info(f"[AGENT DEBUG] Workflow Name: {workflow_ctx.workflow_name}")
        logger.info(f"[AGENT DEBUG] Services extracted: {workflow_ctx.services}")
        logger.info(f"[AGENT DEBUG] Input steps count: {len(workflow_ctx.input_steps)}")
        logger.info(f"[AGENT DEBUG] Variables to collect: {workflow_ctx.get_variables_to_collect()}")
        
        # Log first part of system prompt
        system_prompt = workflow_ctx.generate_system_prompt()
        logger.info(f"[AGENT DEBUG] System prompt (first 500 chars):\n{system_prompt[:500]}...")
        
        # Check for already-present participants first, then wait if none
        participants = list(ctx.room.remote_participants.values())
        if participants:
            participant = participants[0]
            logger.info(f"Found existing participant: {participant.identity}")
        else:
            logger.info("Waiting for participant...")
            participant = await ctx.wait_for_participant()
        logger.info(f"Starting workflow voice assistant for participant: {participant.identity}")
        
        # Create agent session with VAD
        session = AgentSession(
            vad=ctx.proc.userdata.get("vad") if VAD_ENABLED else None,
        )
        _current_session = session
        
        # Set up data message listener for form completion
        @ctx.room.on("data_received")
        def on_data_received(data: bytes, participant, kind):
            """Handle data messages from the backend (e.g., form submissions)."""
            try:
                payload = json.loads(data.decode())
                message_type = payload.get("type", "")
                
                logger.info(f"Received data message: {message_type}")
                
                if message_type == "FORM_SUBMITTED":
                    # The form has been submitted, resume the conversation
                    fields = payload.get("fields_submitted", [])
                    message = f"I've received your submission with the following information: {', '.join(fields)}. Let me process this for you."
                    
                    asyncio.create_task(
                        session.generate_reply(instructions=message)
                    )
                    
            except Exception as e:
                logger.error(f"Error handling data message: {e}")
        
        # Create the agent
        agent = WorkflowVoiceAssistant(workflow_ctx)
        logger.info("Created WorkflowVoiceAssistant")
        
        # Start the session with RoomIO options (REQUIRED for agent to be detected as active)
        logger.info("Starting agent session with RoomIO...")
        await session.start(
            room=ctx.room,
            agent=agent,
            room_input_options=RoomInputOptions(audio_enabled=True),
            room_output_options=RoomOutputOptions(
                audio_enabled=True,
                transcription_enabled=True
            ),
        )
        logger.info("Agent session started successfully")
        
        # Generate greeting with services list
        services = workflow_ctx.services
        if services:
            if len(services) > 1:
                services_text = ", ".join(services[:-1]) + f" or {services[-1]}"
            else:
                services_text = services[0]
            greeting = f"Hello! Welcome to {workflow_ctx.workflow_name}. I can help you with {services_text}. What would you like to do today?"
        else:
            greeting = workflow_ctx.greeting_message or \
                f"Hello! I'm here to help you with {workflow_ctx.workflow_name}. How can I assist you today?"
        
        logger.info(f"Services extracted: {services}")
        
        await session.generate_reply(
            instructions=greeting,
            allow_interruptions=True
        )
        
        logger.info("Workflow voice agent greeting sent")
        
    except Exception as e:
        logger.error(f"Error in entrypoint: {e}", exc_info=True)


def prewarm(proc: JobProcess):
    """Prewarm function to load models before the agent starts."""
    logger.info("Prewarming workflow agent models...")
    
    if VAD_ENABLED:
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
        logger.info(f"Accepting job for room: {room_name}")
        await request.accept()  # MUST call accept() to join the room
    else:
        logger.debug(f"Rejecting job for room: {room_name} (not a voice workflow room)")
        await request.reject()


if __name__ == "__main__":
    """Run the workflow voice agent worker."""
    
    # Validate environment
    if not LIVEKIT_API_KEY or not LIVEKIT_API_SECRET:
        raise ValueError("LIVEKIT_API_KEY2 or LIVEKIT_API_KEY must be set in .env")
    
    if not OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY must be set in .env for LLM, STT, and TTS")
    
    logger.info("=" * 60)
    logger.info("Starting Workflow Voice Agent...")
    logger.info("=" * 60)
    logger.info(f"LiveKit URL: {LIVEKIT_URL}")
    logger.info(f"API Key: {LIVEKIT_API_KEY[:8]}..." if LIVEKIT_API_KEY else "API Key: NOT SET")
    logger.info(f"Room prefix filter: {ROOM_NAME_PREFIX}*")
    logger.info(f"LLM Model: {LLM_MODEL}")
    logger.info(f"TTS Voice: {TTS_VOICE}")
    logger.info(f"STT Language: {STT_LANGUAGE}")
    logger.info(f"VAD Enabled: {VAD_ENABLED}")
    logger.info("=" * 60)
    
    # Run the agent with explicit LiveKit credentials
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=prewarm,
            request_fnc=request_fnc,  # Only accept voice_workflow_ rooms
            ws_url=LIVEKIT_URL,  # Explicitly set the LiveKit server URL
            api_key=LIVEKIT_API_KEY,
            api_secret=LIVEKIT_API_SECRET,
        ),
    )
