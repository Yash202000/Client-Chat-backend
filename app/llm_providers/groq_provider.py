from groq import AsyncGroq
import json
import re
from sqlalchemy.orm import Session
from app.services import credential_service
from app.services.vault_service import vault_service
from app.core.config import settings
from typing import AsyncGenerator, Union, Dict, List
import logging
logger = logging.getLogger(__name__)


def _parse_failed_generation(failed_gen: str, available_tools: list) -> dict | None:
    """
    Parse the <function=name,{...}</function> format that some Groq models
    emit instead of proper JSON tool calls, and return a normalized tool call dict.
    Returns None if parsing fails or the tool isn't in the available list.
    """
    # Handles all formats Groq emits:
    #   <function=name,{"arg": val}</function>
    #   <function=name({"arg": val})</function>
    #   <function=name({"arg": val})></function>
    match = re.search(r'<function=([^,(]+)[,(]\s*({.*})\s*[)>]*</function>', failed_gen, re.DOTALL)
    if not match:
        return None
    func_name = match.group(1).strip()
    func_args_str = match.group(2).strip()
    available_tool_names = [t["function"]["name"] for t in (available_tools or [])]
    if func_name not in available_tool_names:
        return None
    try:
        parameters = json.loads(func_args_str)
    except json.JSONDecodeError:
        return None
    return {
        "type": "tool_call",
        "tool_call_id": f"recovered_{func_name}",
        "tool_name": func_name,
        "parameters": parameters,
        "usage": None
    }

async def generate_response(
    db: Session,
    company_id: int,
    model_name: str,
    system_prompt: str,
    chat_history: list,
    tools: list = None,
    api_key: str = None,
    tool_choice: str = "auto",
    stream: bool = None
) -> Union[Dict, AsyncGenerator[str, None]]:
    # Use settings default if stream parameter is not explicitly set
    if stream is None:
        stream = settings.LLM_STREAMING_ENABLED

    if api_key is None:
        credential = credential_service.get_credential_by_service_name(
            db, service_name="groq", company_id=company_id
        )
        if not credential:
            raise ValueError("Groq API key not found for this company.")
        api_key = vault_service.decrypt(credential.encrypted_credentials)

    client = AsyncGroq(
        api_key=api_key,
        timeout=settings.LLM_REQUEST_TIMEOUT
    )

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(chat_history)

    max_retries = 2
    for attempt in range(max_retries):
        try:
            # STREAMING MODE: Cannot use tools with streaming currently
            if stream and not tools:
                async def stream_response():
                    full_content = ""
                    try:
                        stream_iter = await client.chat.completions.create(
                            messages=messages,
                            model=model_name,
                            stream=True,
                        )

                        async for chunk in stream_iter:
                            if chunk.choices[0].delta.content:
                                token = chunk.choices[0].delta.content
                                full_content += token
                                yield json.dumps({"type": "stream", "content": token})

                        # Send final message indicating completion
                        yield json.dumps({"type": "stream_end", "full_content": full_content})

                    except Exception as e:
                        error_str = str(e)

                        if "tool_use_failed" in error_str or "Failed to call a function" in error_str:
                            pass

                        yield json.dumps({"type": "error", "content": f"LLM provider error: {e}"})

                return stream_response()

            # NON-STREAMING MODE: Original logic with tool support
            chat_completion = await client.chat.completions.create(
                messages=messages,
                model=model_name,
                tools=tools if tools else None,
                tool_choice="auto" if tools else "none",
            )
            response_message = chat_completion.choices[0].message

            # Extract usage data
            usage_data = None
            if hasattr(chat_completion, 'usage') and chat_completion.usage:
                usage_data = {
                    "prompt_tokens": chat_completion.usage.prompt_tokens,
                    "completion_tokens": chat_completion.usage.completion_tokens,
                    "total_tokens": chat_completion.usage.total_tokens
                }

            # Handle tool calls
            if response_message.tool_calls:
                available_tool_names = [t["function"]["name"] for t in (tools or [])]
                tool_calls = []

                for call in response_message.tool_calls:
                    tool_name = call.function.name
                    if tool_name not in available_tool_names:
                        error_message = (
                            f"You attempted to call '{tool_name}', which is not available. "
                            f"Please choose only from: {', '.join(available_tool_names)}."
                        )
                        # Add LLM's bad attempt + corrective instruction
                        messages.append({
                            "role": "system",
                            "content": response_message.content or "",
                        })
                        messages.append({"role": "system", "content": error_message})

                        break  # trigger retry
                    else:
                        tool_calls.append({
                            "type": "tool_call",
                            "tool_call_id": call.id,
                            "tool_name": tool_name,
                            "parameters": json.loads(call.function.arguments),
                            "usage": usage_data
                        })

                if tool_calls:
                    if len(tool_calls) == 1:
                        return tool_calls[0]
                    return tool_calls

                continue  # retry if invalid tool was detected

            # If no tool call, return plain text
            # Check if content contains malformed function syntax (model hallucinating tool calls)
            content = response_message.content or ""
            if content and ("<function=" in content or "</function>" in content):
                if tools:
                    recovered = _parse_failed_generation(content, tools)
                    if recovered:
                        recovered["usage"] = usage_data
                        return recovered
                return {"type": "text", "content": "I apologize, but I'm having technical difficulties processing your request. Could you please try again?", "usage": usage_data}

            return {"type": "text", "content": content, "usage": usage_data}

        except Exception as e:
            error_str = str(e)

            # Tool use failed — try to recover by parsing the failed_generation field
            if "tool_use_failed" in error_str or "Failed to call a function" in error_str:
                try:
                    body = getattr(e, 'body', None)
                    if isinstance(body, dict):
                        failed_gen = body.get('error', {}).get('failed_generation', '')
                    elif hasattr(e, 'response'):
                        body = e.response.json()
                        failed_gen = body.get('error', {}).get('failed_generation', '')
                    else:
                        failed_gen = ''

                    if failed_gen and tools:
                        recovered = _parse_failed_generation(failed_gen, tools)
                        if recovered:
                            return recovered
                except Exception as parse_err:
                    logger.exception(parse_err)


            return {"type": "text", "content": f"LLM provider error: {e}"}

    return {
        "type": "text",
        "content": "I had trouble selecting a valid tool. Could you rephrase your request?"
    }
