import os
from sqlalchemy.orm import Session
from app.services import agent_service, chat_service, tool_service, tool_execution_service, workflow_execution_service, workflow_service, widget_settings_service, credential_service
from app.core.config import settings
from app.models.chat_message import ChatMessage
from app.schemas.chat_message import ChatMessage as ChatMessageSchema, ChatMessageCreate
import json
from app.services.connection_manager import manager
from app.services.vault_service import vault_service
from app.models.agent import Agent

import numpy as np
import chromadb
from app.llm_providers import gemini_provider, nvidia_provider, nvidia_api_provider, groq_provider, openai_provider
from app.services.faiss_vector_database import VectorDatabase
from app.llm_providers.nvidia_api_provider import NVIDIAEmbeddings
from app.core.object_storage import s3_client, chroma_client


def _get_embeddings(agent: Agent, texts: list[str]):
    """
    Generates embeddings for a list of texts using the agent's configured embedding model.
    """
    print(f"Generating embeddings for {len(texts)} texts using {agent.embedding_model}...")
    
    if agent.embedding_model == 'gemini':
        embeddings = []
        for text in texts:
            try:
                result = gemini_provider.genai.embed_content(model="models/embedding-001", content=text, task_type="RETRIEVAL_DOCUMENT")
                embeddings.append(result['embedding'])
            except Exception as e:
                print(f"An error occurred while embedding text with Gemini: {e}")
                embeddings.append(np.zeros(768)) # Gemini's embedding dimension
        return np.array(embeddings)
    
    elif agent.embedding_model == 'nvidia':
        try:
            # Attempt to use local NVIDIA model
            return nvidia_provider.get_embeddings(texts)
        except Exception as e:
            print(f"An error occurred while embedding text with local NVIDIA model: {e}")
            print("Attempting to fallback to NVIDIA API for embeddings...")
            try:
                # Fallback to NVIDIA API
                client = nvidia_api_provider.NVIDIAEmbeddings()
                return np.array(client.embed_documents(texts))
            except Exception as api_e:
                print(f"Fallback to NVIDIA API also failed: {api_e}")
                return np.array([np.zeros(1024) for _ in texts]) # Final fallback: placeholder
    
    elif agent.embedding_model == 'nvidia_api':
        try:
            client = nvidia_api_provider.NVIDIAEmbeddings()
            return np.array(client.embed_documents(texts))
        except Exception as e:
            print(f"An error occurred while embedding text with NVIDIA API: {e}")
            return np.array([np.zeros(1024) for _ in texts]) # Placeholder dimension for NVIDIA
            
    else:
        raise ValueError(f"Unknown embedding model: {agent.embedding_model}")


def _get_rag_context(agent: Agent, user_query: str, knowledge_bases: list, k: int = 3):
    """
    Performs retrieval from the appropriate knowledge bases and returns the augmented context.
    """
    if not knowledge_bases:
        return ""

    all_retrieved_chunks = []
    query_embedding = _get_embeddings(agent, [user_query])[0]

    for kb in knowledge_bases:
        try:
            print(kb.type, kb.provider, kb.connection_details, kb.chroma_collection_name, kb.faiss_index_id)
            if kb.type == "local" and kb.chroma_collection_name:
                # Query the local ChromaDB collection managed by our pipeline
                collections = chroma_client.list_collections() # Debug line to ensure connection
                print(f"Available collections: {[col.name for col in collections]}")
                print(chroma_client.count_collections())
                collection = chroma_client.get_collection(name=kb.chroma_collection_name)
                results = collection.query(
                    query_embeddings=[query_embedding.tolist()],
                    n_results=k
                )
                all_retrieved_chunks.extend(results['documents'][0])

            elif kb.type == "local" and kb.faiss_index_id:
                # Query the local FAISS index
                embeddings_instance = NVIDIAEmbeddings() # Assuming NVIDIAEmbeddings is the chosen embedding model
                faiss_db_path = os.path.join(settings.FAISS_INDEX_DIR, str(agent.company_id), kb.faiss_index_id)
                faiss_db = VectorDatabase(embeddings=embeddings_instance, db_path=faiss_db_path, index_name=kb.faiss_index_id)
                if faiss_db.load_index():
                    # FAISS similarity search expects a string query, not an embedding
                    results = faiss_db.similarity_search(user_query, k=k)
                    all_retrieved_chunks.extend([doc.page_content for doc in results])
                else:
                    print(f"Error loading FAISS index from {faiss_db_path}")

            elif kb.type == "remote" and kb.provider == "chroma" and kb.connection_details:
                # Query a user-provided, remote ChromaDB instance
                client = chromadb.HttpClient(host=kb.connection_details.get("host"), port=kb.connection_details.get("port"))
                collection = client.get_collection(name=kb.connection_details.get("collection_name"))
                results = collection.query(
                    query_embeddings=[query_embedding.tolist()],
                    n_results=k
                )
                all_retrieved_chunks.extend(results['documents'][0])
        except Exception as e:
            print(f"Error querying knowledge base {kb.name} (ID: {kb.id}): {e}")

    if not all_retrieved_chunks:
        return ""

    context = "\n\n---\n\n".join(all_retrieved_chunks)
    return context


class CustomJsonEncoder(json.JSONEncoder):
    def default(self, o):
        if hasattr(o, 'result'):
             return o.result
        try:
            return super().default(o)
        except TypeError:
            return str(o)



PROVIDER_MAP = {
    "groq": groq_provider,
    "gemini": gemini_provider,
    "openai": openai_provider,
}

def format_chat_history(chat_messages: list) -> list[dict[str, str]]:
    """
    Formats the chat history from various possible types (SQLAlchemy models, dicts)
    into a standardized list of dictionaries with 'role' and 'content' keys.
    """
    history = []
    for msg in chat_messages:
        try:
            if hasattr(msg, 'sender') and hasattr(msg, 'message'):
                sender = msg.sender
                message = msg.message
            elif isinstance(msg, dict) and 'sender' in msg and 'message' in msg:
                sender = msg['sender']
                message = msg['message']
            else:
                continue

            role = "assistant" if sender == "agent" else sender
            history.append({"role": role, "content": message})
        except (AttributeError, TypeError) as e:
            print(f"Skipping malformed message in history: {msg}, error: {e}")
            continue
    return history


import asyncio
from fastmcp.client import Client

def _sanitize_schema_for_openai(schema: dict) -> dict:
    """
    Removes OpenAI-incompatible schema properties like anyOf, oneOf, allOf, enum, not at the top level.
    Returns a sanitized copy of the schema.
    """
    if not isinstance(schema, dict):
        return schema

    # Create a copy to avoid modifying the original
    sanitized = schema.copy()

    # Remove incompatible top-level keys
    incompatible_keys = ['anyOf', 'oneOf', 'allOf', 'enum', 'not']
    for key in incompatible_keys:
        if key in sanitized:
            print(f"[SCHEMA SANITIZATION] Removing '{key}' from schema for OpenAI compatibility")
            del sanitized[key]

    return sanitized

async def _get_tools_for_agent(agent, db: Session = None, company_id: int = None):
    """
    Builds a list of tool definitions for the LLM, including custom, MCP, built-in tools,
    and workflows as callable functions.
    Uses provider-specific schemas for compatibility.
    Built-in tools are now configurable per agent (added from agent.tools).
    Workflows are presented as functions so LLM can decide when to trigger them.
    """
    tool_definitions = []

    # Determine if we need OpenAI-compatible schemas
    is_openai = agent.llm_provider == "openai"

    for tool in agent.tools:
        if tool.tool_type == "builtin":
            # Built-in tools - use stored parameters with provider-specific adjustments
            params = tool.parameters or {"type": "object", "properties": {}}

            # Special handling for create_or_update_contact with OpenAI
            if tool.name == "create_or_update_contact" and not is_openai:
                # For Groq and Gemini, we can use anyOf
                params = dict(params)  # Make a copy
                params["anyOf"] = [
                    {"required": ["name"]},
                    {"required": ["email"]},
                    {"required": ["phone_number"]}
                ]

            if is_openai:
                params = _sanitize_schema_for_openai(params)

            tool_definitions.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": params,
                },
            })
        elif tool.tool_type == "custom":
            # Sanitize parameters for OpenAI if needed
            params = tool.parameters or {}
            if is_openai:
                params = _sanitize_schema_for_openai(params)

            tool_definitions.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": params,
                },
            })
        elif tool.tool_type == "mcp" and tool.mcp_server_url:
            try:
                async with Client(str(tool.mcp_server_url)) as client:
                    mcp_tools = await client.list_tools()
                for mcp_tool in mcp_tools:
                    # Simplify the complex MCP schema for the LLM
                    ref_name = mcp_tool.inputSchema.get('properties', {}).get('params', {}).get('$ref', '').split('/')[-1]
                    simple_params_schema = mcp_tool.inputSchema.get('$defs', {}).get(ref_name, {})

                    if not simple_params_schema:
                         # Fallback to the original schema if simplification fails
                        simple_params_schema = mcp_tool.inputSchema

                    # Sanitize MCP schema for OpenAI if needed
                    if is_openai:
                        simple_params_schema = _sanitize_schema_for_openai(simple_params_schema)

                    tool_description = mcp_tool.description or f"No description available for {mcp_tool.name}."
                    tool_definitions.append({
                        "type": "function",
                        "function": {
                            "name": f"{tool.name.replace(' ', '_')}__{mcp_tool.name.replace(' ', '_')}",
                            "description": tool_description,
                            "parameters": simple_params_schema,
                        },
                    })
            except Exception as e:
                print(f"Error fetching tools from MCP server {tool.mcp_server_url}: {e}")

    # Add workflows as callable functions (LLM-driven routing)
    if db and company_id:
        try:
            active_workflows = workflow_service.get_workflows(db, company_id)
            for workflow in active_workflows:
                if not workflow.is_active:
                    continue

                # Build description with trigger hints
                description = workflow.description or f"Start the {workflow.name} process"
                if workflow.trigger_phrases:
                    hints = ", ".join(workflow.trigger_phrases[:5])
                    description += f". Use when user says things like: {hints}"

                workflow_func = {
                    "type": "function",
                    "function": {
                        "name": f"start_workflow_{workflow.id}",
                        "description": description,
                        "parameters": {
                            "type": "object",
                            "properties": {},
                            "required": []
                        }
                    }
                }
                tool_definitions.append(workflow_func)
                print(f"[TOOLS] Added workflow function: start_workflow_{workflow.id} ({workflow.name})")
        except Exception as e:
            print(f"Error adding workflow functions: {e}")

    print(f"Final tool definitions for LLM: {json.dumps(tool_definitions, indent=2)}")
    return tool_definitions

async def generate_agent_response(db: Session, agent_id: int, session_id: str, boradcast_session_id: str, company_id: int, user_message: str):
    """
    Orchestrates the agent's response, handling tool use and broadcasting messages.
    - If a tool is called, it broadcasts a 'tool_use' message, executes the tool,
      then gets a final response from the LLM, which it saves and broadcasts.
    - If no tool is called, it saves and broadcasts the text response directly.
    - This function no longer returns the response text to the caller.
    """
    agent = agent_service.get_agent(db, agent_id, company_id)
    if not agent:
        print(f"Error: Agent not found for agent_id {agent_id}")
        return

    print(f"DEBUG: Agent retrieved: {agent.name}, Tools: {agent.tools}")

    provider_module = PROVIDER_MAP.get(agent.llm_provider)
    if not provider_module:
        print(f"Error: LLM provider '{agent.llm_provider}' not found.")
        return

    # Get RAG context
    rag_context = _get_rag_context(agent, user_message, agent.knowledge_bases)

    generic_tools = await _get_tools_for_agent(agent, db=db, company_id=company_id)
    db_chat_history = chat_service.get_chat_messages(db, agent_id, boradcast_session_id, company_id, limit=20)
    formatted_history = format_chat_history(db_chat_history)
    formatted_history.append({"role": "user", "content": user_message})

    # Check if this is the first message in the conversation (no assistant messages yet)
    is_first_message = not any(msg.get("role") == "assistant" for msg in formatted_history)

    print(f"[AGENT EXECUTION DEBUG] Session: {boradcast_session_id}")
    print(f"[AGENT EXECUTION DEBUG] Formatted history length: {len(formatted_history)}")
    print(f"[AGENT EXECUTION DEBUG] Is first message: {is_first_message}")
    print(f"[AGENT EXECUTION DEBUG] History roles: {[msg.get('role') for msg in formatted_history]}")
    print(f"[AGENT EXECUTION DEBUG] LLM Provider: {agent.llm_provider}")

    # Note: Typing indicator is now handled at the WebSocket endpoint level
    # to ensure it shows immediately after user message (not here which is later in the flow)

    try:
        # Look up credential by LLM provider for the company
        agent_api_key = None
        llm_credential = credential_service.get_credential_by_service_name(db, agent.llm_provider, company_id)
        if llm_credential:
            print(f"Found {agent.llm_provider} credential in vault for company.")
            agent_api_key = credential_service.get_decrypted_credential(db, llm_credential.id, company_id)
        else:
            print(f"{agent.llm_provider} credential not found in vault for company. LLM will use provider's default or fail.")

        # Build base system prompt
        system_prompt = (
            "You are a helpful and precise assistant. Your primary goal is to assist users by using the tools provided. "
            "Follow these rules strictly:\n"
            "1. Examine the user's request to determine the appropriate tool.\n"
            "2. Look at the tool's schema to understand its required parameters.\n"
            "3. If the user has provided all the necessary parameters, call the tool.\n"
            "4. **Crucially, if the user has NOT provided all required parameters, you **MUST** ask for the missing information using **natural language**. Do NOT guess, do NOT use placeholders, and do NOT call the tool without the required information.**\n"
            "5. You ONLY have access to the following tools, and should NEVER make up tools that are not listed here: "
            "6. For example, if a tool requires a 'user\_id', and the user asks to 'get user details', you must respond with: 'I can certainly help you find those details. Could you please provide the user's ID?'\n"
            "7. If a tool the user requests is conceptually unavailable (like 'list all orders' when only 'get order by ID' is available), explain the limitation in **simple, non-technical terms** and offer the alternative tool without mentioning the function names.\n"
            "8. **HUMAN HANDOFF**: If the user explicitly asks to speak with a human agent, or if the issue becomes too complex for you to handle, use the 'request_human_handoff' tool. Provide a clear summary of the conversation so the human agent can quickly understand the context.\n"
        )

        # Add contact collection instruction - emphasize more strongly for first message
        if is_first_message:
            system_prompt += (
                "9. **CONTACT INFORMATION COLLECTION (CRITICAL - THIS IS THE FIRST MESSAGE)**: \n"
                "   THIS IS THE USER'S FIRST MESSAGE. You MUST immediately call 'get_contact_info' BEFORE responding to anything else.\n"
                "   Your FIRST action must be to call the 'get_contact_info' tool. DO NOT greet the user or respond to their message until you do this.\n"
                "   After calling 'get_contact_info':\n"
                "   a) If we have complete info (name AND email AND phone), greet them by name and proceed with helping them\n"
                "   b) If ANY field is missing (name, email, OR phone), you MUST collect ALL missing fields one by one:\n"
                "      - Missing name? Ask: 'To get started, may I have your name?'\n"
                "      - Missing email? Ask: 'Great! And what's your email address?'\n"
                "      - Missing phone? Ask: 'Perfect! Lastly, what's your phone number?'\n"
                "   c) After EACH piece of information is provided, IMMEDIATELY call 'create_or_update_contact' to save it\n"
                "   d) DO NOT proceed with their actual request until you have collected ALL THREE fields\n"
                "   e) Only after you have name, email, AND phone number should you ask 'How can I help you today?'\n"
                "   REMEMBER: Your VERY FIRST ACTION must be to call 'get_contact_info'. No exceptions.\n"
            )
        else:
            system_prompt += (
                "9. **CONTACT INFORMATION COLLECTION (ONGOING)**: \n"
                "   Continue collecting any missing contact information (name, email, phone) if not yet complete.\n"
                "   After EACH piece of information is provided, IMMEDIATELY call 'create_or_update_contact' to save it.\n"
                "   Only proceed with the user's request once all three fields are collected.\n"
            )

        system_prompt += (
            "For example, if the user asks to 'get user details' and the 'get_user_details' tool requires a 'user_id', you must respond by asking 'I can do that. What is the user's ID?'\n"
            f"The user's request will be provided next. Current system instructions: {agent.prompt}"
        )
        if rag_context:
            system_prompt += f"\n\nHere is some context from the knowledge base that might be relevant:\n{rag_context}"

        MAX_HISTORY = 10
        formatted_history = formatted_history[-MAX_HISTORY:]

        # For first message, force the AI to call get_contact_info
        tool_choice_param = "auto"  # Default
        if is_first_message and agent.llm_provider == "openai":
            # Force OpenAI to call get_contact_info on first message
            tool_choice_param = {
                "type": "function",
                "function": {"name": "get_contact_info"}
            }
            print(f"[AGENT EXECUTION] First message detected - forcing get_contact_info tool call")

        # Call LLM provider asynchronously (disable streaming when using tools)
        llm_response = await provider_module.generate_response(
            db=db, company_id=company_id, model_name=agent.model_name,
            system_prompt=system_prompt, chat_history=formatted_history,
            tools=generic_tools, api_key=agent_api_key,
            tool_choice=tool_choice_param,
            stream=False  # Disable streaming when tools are enabled
        )
    except Exception as e:
        print(f"LLM Provider Error: {e}")
        # Return handoff type so caller can initiate human agent handoff
        return {
            "type": "handoff",
            "reason": f"AI routing unavailable: {str(e)}"
        }
    finally:
        # Typing indicator OFF is handled at WebSocket endpoint level (in finally block)
        pass

    final_agent_response_text = None
    tool_name = None
    tool_result = None

    # Handle both single tool call (dict) and multiple tool calls (list)
    if isinstance(llm_response, list):
        # Multiple tool calls - process the first one for now
        # TODO: Handle multiple tool calls in sequence
        llm_response = llm_response[0]
        print(f"[Agent Execution] Warning: Multiple tool calls detected, processing first one only")

    if llm_response.get('type') == 'tool_call':
        tool_name = llm_response.get('tool_name')
        parameters = llm_response.get('parameters', {})
        tool_call_id = llm_response.get('tool_call_id')

        # Check if LLM decided to trigger a workflow
        if tool_name and tool_name.startswith("start_workflow_"):
            workflow_id = int(tool_name.replace("start_workflow_", ""))
            print(f"[AGENT EXECUTION] LLM triggered workflow {workflow_id}")
            return {
                "type": "workflow_trigger",
                "workflow_id": workflow_id,
                "message": user_message
            }

        tool_call_msg = {
            "message_type": "tool_use",
            "tool_call": {"id": tool_call_id, "type": "function", "function": {"name": tool_name, "arguments": json.dumps(parameters)}}
        }
        await manager.broadcast_to_session(boradcast_session_id, json.dumps(tool_call_msg), "agent")

        # --- Tool Execution ---
        tool_result = await tool_execution_service.execute_tool(
            db=db,
            tool_name=tool_name,
            parameters=parameters,
            session_id=boradcast_session_id,
            company_id=company_id
        )

        if tool_result is None or "error" in tool_result and "not found" in tool_result.get("error", ""):
            print(f"[AGENT EXECUTION] Tool '{tool_name}' not found or failed to execute.")
            return
        
        result_content = tool_result.get('result', tool_result.get('error', 'No output'))

        # Check if tool provided a formatted response (optimization for contact tools)
        if 'formatted_response' in tool_result:
            # Use pre-formatted response directly, skip second LLM call
            final_agent_response_text = tool_result['formatted_response']
            print(f"[AGENT EXECUTION] Using pre-formatted response from tool, skipping LLM call")
            print(f"[AGENT EXECUTION] Formatted response: {final_agent_response_text}")
        else:
            # --- Get Final Response from LLM ---
            assistant_message = {"role": "assistant", "content": None, "tool_calls": [{"id": tool_call_id, "type": "function", "function": {"name": tool_name, "arguments": json.dumps(parameters)}}]}
            tool_response_message = {"role": "tool", "tool_call_id": tool_call_id, "name": tool_name, "content": json.dumps(result_content, cls=CustomJsonEncoder)}

            formatted_history.append(assistant_message)
            formatted_history.append(tool_response_message)

            # Build context-aware prompt based on which tool was called
            if tool_name == "get_contact_info":
                # Special handling for contact info tool
                final_response_prompt = (
                    "You just called the 'get_contact_info' tool to check what contact information we have for this user. "
                    "The tool result is in the chat history. "
                    "Based on the result:\n"
                    "- If contact is null (None), it means we have NO information. Ask for their name: 'To get started, may I have your name?'\n"
                    "- If contact exists but name is missing/null, ask: 'To get started, may I have your name?'\n"
                    "- If contact exists but email is missing/null, ask: 'Great! And what's your email address?'\n"
                    "- If contact exists but phone_number is missing/null, ask: 'Perfect! Lastly, what's your phone number?'\n"
                    "- If all three fields exist (name, email, phone_number), greet them warmly by name and ask 'How can I help you today?'\n"
                    "IMPORTANT: Ask for ONE missing field at a time. Do NOT ask for all fields at once.\n"
                    "Do NOT mention tools, APIs, or technical details. Keep it natural and conversational."
                )
            elif tool_name == "create_or_update_contact":
                # Special handling for contact creation/update tool
                final_response_prompt = (
                    "You just saved contact information using the 'create_or_update_contact' tool. "
                    "The tool result shows which fields were saved. Look at the contact data in the tool result.\n"
                    "Now check what's STILL MISSING:\n"
                    "- If name is null/missing: Ask 'To get started, may I have your name?'\n"
                    "- If email is null/missing: Ask 'Great! And what's your email address?'\n"
                    "- If phone_number is null/missing: Ask 'Perfect! Lastly, what's your phone number?'\n"
                    "- If ALL THREE fields now exist (name, email, phone_number), thank them and ask 'How can I help you today?'\n"
                    "CRITICAL: You MUST collect all three fields (name, email, phone) before asking how you can help.\n"
                    "Ask for ONE missing field at a time. Do NOT skip any fields.\n"
                    "Do NOT mention tools, APIs, or technical details. Keep it natural and conversational."
                )
            else:
                # Standard prompt for other tools
                final_response_prompt = (
                    "You have just successfully used a tool to retrieve information for the user. "
                    "The user's original query and the data from the tool are in the chat history. "
                    "Your task is to synthesize this information into a concise, natural, and helpful response. "
                    "Do NOT mention the tool name, tool IDs, or the fact that you are processing a tool result. "
                    "Simply provide a direct and clear answer to the user's question based on the data."
                )

            # Call LLM provider asynchronously for final response (disable streaming for tool result processing)
            final_response = await provider_module.generate_response(
                db=db, company_id=company_id, model_name=agent.model_name,
                system_prompt=final_response_prompt, chat_history=formatted_history,
                tools=[], api_key=agent_api_key,
                stream=False  # Disable streaming for tool result processing
            )
            final_agent_response_text = final_response.get('content', 'No response content.')

    elif llm_response.get('type') == 'text':
        final_agent_response_text = llm_response.get('content', 'No response content.')

    # --- Return Final Message ---
    # Note: Message saving and broadcasting is handled by the caller (e.g., public_voice.py)
    if final_agent_response_text and final_agent_response_text.strip():
        print(f"[AgentResponse] Generated response text: {final_agent_response_text[:100]}...")
    else:
        print(f"[AgentResponse] Final agent response was empty.")

    # Return response with call info if handoff tool was used
    if tool_name == "request_human_handoff" and tool_result.get('result', {}).get('status') == 'call_initiated':
        result_data = tool_result.get('result', {})
        return {
            "text": final_agent_response_text,
            "call_initiated": True,
            "agent_name": result_data.get('agent_name'),
            "room_name": result_data.get('room_name'),
            "livekit_url": result_data.get('livekit_url'),
            "user_token": result_data.get('user_token')
        }

    return final_agent_response_text


async def generate_agent_response_stream(db: Session, agent_id: int, session_id: str, boradcast_session_id: str, company_id: int, user_message: str):
    """
    Streaming version of generate_agent_response.
    Yields tokens as they arrive from the LLM for real-time user experience.
    Note: Streaming is ONLY supported for text responses (no tool calls).
    If tools are needed, falls back to non-streaming mode.
    """
    agent = agent_service.get_agent(db, agent_id, company_id)
    if not agent:
        print(f"Error: Agent not found for agent_id {agent_id}")
        return

    provider_module = PROVIDER_MAP.get(agent.llm_provider)
    if not provider_module:
        print(f"Error: LLM provider '{agent.llm_provider}' not found.")
        return

    # Get RAG context
    rag_context = _get_rag_context(agent, user_message, agent.knowledge_bases)

    generic_tools = await _get_tools_for_agent(agent, db=db, company_id=company_id)
    db_chat_history = chat_service.get_chat_messages(db, agent_id, boradcast_session_id, company_id, limit=20)
    formatted_history = format_chat_history(db_chat_history)
    formatted_history.append({"role": "user", "content": user_message})

    is_first_message = not any(msg.get("role") == "assistant" for msg in formatted_history)

    # If tools are present or it's first message (requires tool call), fall back to non-streaming
    if generic_tools or is_first_message:
        print(f"[STREAMING] Tools detected or first message - falling back to non-streaming mode")
        # Call non-streaming version and yield the complete response
        response = await generate_agent_response(db, agent_id, session_id, boradcast_session_id, company_id, user_message)
        if response:
            yield json.dumps({"type": "complete", "content": response})
        return

    try:
        # Look up credential by LLM provider for the company
        agent_api_key = None
        llm_credential = credential_service.get_credential_by_service_name(db, agent.llm_provider, company_id)
        if llm_credential:
            print(f"Found {agent.llm_provider} credential in vault for company (streaming).")
            agent_api_key = credential_service.get_decrypted_credential(db, llm_credential.id, company_id)
        else:
            print(f"{agent.llm_provider} credential not found in vault for company (streaming). LLM will use provider's default or fail.")

        system_prompt = (
            "You are a helpful and precise assistant. "
            f"Current system instructions: {agent.prompt}"
        )
        if rag_context:
            system_prompt += f"\n\nHere is some context from the knowledge base that might be relevant:\n{rag_context}"

        MAX_HISTORY = 10
        formatted_history = formatted_history[-MAX_HISTORY:]

        # Call LLM provider with streaming enabled
        llm_response = await provider_module.generate_response(
            db=db, company_id=company_id, model_name=agent.model_name,
            system_prompt=system_prompt, chat_history=formatted_history,
            tools=None,  # No tools in streaming mode
            api_key=agent_api_key,
            stream=True  # Enable streaming
        )

        # Check if response is a generator (streaming) or dict (non-streaming fallback)
        if hasattr(llm_response, '__aiter__'):
            # Stream tokens as they arrive
            async for token_json in llm_response:
                yield token_json
        else:
            # Fallback to non-streaming if provider doesn't support streaming
            content = llm_response.get('content', '')
            yield json.dumps({"type": "complete", "content": content})

    except Exception as e:
        print(f"LLM Streaming Error: {e}")
        yield json.dumps({"type": "error", "content": f"Error: {str(e)}"})