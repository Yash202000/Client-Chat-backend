
from app.llm_providers.gemini_provider import generate_response as ggr
from app.llm_providers.groq_provider import generate_response as grg
from app.llm_providers.openai_provider import generate_response as oai
from app.services import knowledge_base_service
from app.services.prompt_guard_service import prompt_guard, get_safe_system_prompt
from sqlalchemy.orm import Session
from fastmcp.client import Client
import asyncio
import json
import logging

logger = logging.getLogger(__name__)


class LLMToolService:
    def __init__(self, db: Session):
        self.db = db

    async def execute(self, model: str, system_prompt: str, chat_history: list, user_prompt: str, tools: list, knowledge_base_id: int = None, company_id: int = None, attachments: list = None, session_id: str = None):
        """
        This is the core logic for handling LLM interactions. It builds the prompt,
        formats tools, and manages a validation/retry loop to ensure the LLM
        behaves correctly.

        Args:
            attachments: List of attachment dicts with file_name, file_type, file_size, file_data (base64)
            session_id: Optional session ID for rate limiting
        """
        # === SECURITY: Scan user input for prompt injection ===
        scan_result = prompt_guard.scan_message(user_prompt, check_off_topic=True)
        if not scan_result.is_safe:
            logger.warning(f"[LLMToolService] Blocked injection attempt: {scan_result.detected_patterns}")
            return {
                "type": "text",
                "content": "I'm sorry, but I couldn't process that request. Please rephrase your question."
            }
        # Use sanitized message
        user_prompt = scan_result.sanitized_message
        # === END SECURITY ===

        # 1. --- Construct the master System Prompt with security hardening ---
        base_instructions = (
            "You are a helpful and precise assistant. Your primary goal is to assist users by using the tools provided. "
            "Follow these rules strictly:\n"
            "1. Examine the user's request to determine the appropriate tool from the provided list.\n"
            "2. Look at the tool's schema to understand its required parameters.\n"
            "3. If the user has provided all the necessary parameters, call the tool.\n"
            "4. **Crucially, if the user has NOT provided all required parameters, you MUST ask the user for the missing information. Do NOT guess, do NOT use placeholders, and do NOT call the tool without the required information.**\n"
            "For example, if the user asks to 'get user details' and the 'get_user_details' tool requires a 'user_id', you must respond by asking 'I can do that. What is the user's ID?'\n"
            f"Base instructions for this conversation: {system_prompt}"
        )

        # Apply security hardening to system prompt
        final_system_prompt = get_safe_system_prompt(base_instructions)

        # 2. --- Augment Prompt with Knowledge Base Context (if applicable) ---
        augmented_prompt = user_prompt
        if knowledge_base_id:
            relevant_chunks = knowledge_base_service.find_relevant_chunks(
                self.db, knowledge_base_id, company_id, user_prompt
            )
            if relevant_chunks:
                context = "\n\nContext:\n" + "\n".join(relevant_chunks)
                augmented_prompt = f"{user_prompt}{context}"
                print(f"DEBUG: Augmented prompt with KB context.")

        # Build user message content - support image attachments for vision models
        if attachments:
            # Build multimodal content array for vision models
            content = [{"type": "text", "text": augmented_prompt}]
            for attachment in attachments:
                file_type = attachment.get('file_type', '')
                if file_type.startswith('image/'):
                    content.append({
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{file_type};base64,{attachment['file_data']}"
                        }
                    })
                    print(f"DEBUG: Added image attachment to LLM request: {attachment.get('file_name')}")
            user_message = {"role": "user", "content": content}
        else:
            user_message = {"role": "user", "content": augmented_prompt}

        full_chat_history = chat_history + [user_message]

        # 3. --- Format all tools for the LLM Provider ---
        formatted_tools = []
        for tool in tools:
            if tool.tool_type == 'custom':
                formatted_tools.append(tool.schema_ or {})
            elif tool.tool_type == 'mcp' and tool.mcp_server_url:
                try:
                    async with Client(str(tool.mcp_server_url)) as client:
                        mcp_tools = await client.list_tools()
                    for mcp_tool in mcp_tools:
                        ref_name = mcp_tool.inputSchema.get('properties', {}).get('params', {}).get('$ref', '').split('/')[-1]
                        params_schema = mcp_tool.inputSchema.get('$defs', {}).get(ref_name, {})
                        formatted_tools.append({
                            "type": "function",
                            "function": {
                                "name": f"{tool.name.replace(' ', '_')}___{mcp_tool.name.replace(' ', '_')}",
                                "description": mcp_tool.description,
                                "parameters": params_schema,
                            },
                        })
                except Exception as e:
                    print(f"ERROR: Failed to fetch tools from MCP server {tool.mcp_server_url}. Error: {e}")
        
        print(f"DEBUG: Total formatted tools sent to LLM: {len(formatted_tools)}")

        # 4. --- Execute with Validation and Retry Loop ---
        provider_name, model_name = model.split('/')
        if provider_name == "groq":
            provider_module = grg
        elif provider_name == "openai":
            provider_module = oai
        else:
            provider_module = ggr  # default to gemini
        max_retries = 2

        for attempt in range(max_retries):
            response = await provider_module(
                db=self.db, company_id=company_id, model_name=model_name,
                system_prompt=final_system_prompt, chat_history=full_chat_history,
                tools=formatted_tools,
                stream=False  # Disable streaming for workflow execution
            )

            if response.get('type') == 'tool_call':
                tool_name = response.get('tool_name')
                available_tool_names = [t['function']['name'] for t in formatted_tools]

                if tool_name in available_tool_names:
                    return response  # Success, exit the loop

                # --- Invalid tool, construct corrective prompt and retry ---
                error_message = f"You tried to call a tool named '{tool_name}', but that tool does not exist. Please choose a tool from the following available list: {', '.join(available_tool_names)}. Or, ask the user for clarification."
                
                # Add the LLM's failed attempt and our correction to the history
                full_chat_history.append({"role": "assistant", "content": None, "tool_calls": [{"id": response.get('tool_call_id'), "type": "function", "function": {"name": tool_name, "arguments": json.dumps(response.get('parameters', {}))}}]})
                full_chat_history.append({"role": "system", "content": error_message})
                
                print(f"DEBUG: Invalid tool '{tool_name}'. Retrying... (Attempt {attempt + 1}/{max_retries})")
                continue  # Retry the call with the updated history
            
            else: # It's a text response, so we're done
                return response

        # If all retries fail, return a final error message
        return {"type": "text", "content": "I am having trouble selecting the correct tool. Could you please rephrase your request?"}
