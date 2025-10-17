from groq import Groq
import json
from sqlalchemy.orm import Session
from app.services import credential_service
from app.services.vault_service import vault_service

def generate_response(db: Session, company_id: int, model_name: str, system_prompt: str, chat_history: list, tools: list = None, api_key: str = None):
    if api_key is None:
        credential = credential_service.get_credential_by_service_name(
            db, service_name="groq", company_id=company_id
        )
        if not credential:
            raise ValueError("Groq API key not found for this company.")
        api_key = vault_service.decrypt(credential.encrypted_credentials)

    client = Groq(api_key=api_key)

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(chat_history)

    max_retries = 2
    for attempt in range(max_retries):
        try:
            chat_completion = client.chat.completions.create(
                messages=messages,
                model=model_name,
                tools=tools if tools else None,
                tool_choice="auto" if tools else "none",
            )
            response_message = chat_completion.choices[0].message

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
                        # Add LLM’s bad attempt + corrective instruction
                        messages.append({
                            "role": "system",
                            "content": response_message.content or "",
                        })
                        messages.append({"role": "system", "content": error_message})

                        print(f"DEBUG: Invalid tool '{tool_name}'. Retrying... (Attempt {attempt+1}/{max_retries})")
                        break  # trigger retry
                    else:
                        tool_calls.append({
                            "type": "tool_call",
                            "tool_call_id": call.id,
                            "tool_name": tool_name,
                            "parameters": json.loads(call.function.arguments),
                        })

                if tool_calls:
                    return tool_calls if len(tool_calls) > 1 else tool_calls[0]

                continue  # retry if invalid tool was detected

            # If no tool call, return plain text
            return {"type": "text", "content": response_message.content}

        except Exception as e:
            print(f"Groq API Error: {e}")
            return {"type": "text", "content": f"LLM provider error: {e}"}

    return {
        "type": "text",
        "content": "I had trouble selecting a valid tool. Could you rephrase your request?"
    }
