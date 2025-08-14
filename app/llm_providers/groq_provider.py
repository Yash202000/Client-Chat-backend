from groq import Groq
import json
from sqlalchemy.orm import Session
from app.services import credential_service

def generate_response(db: Session, company_id: int, model_name: str, system_prompt: str, chat_history: list, tools: list = None, api_key: str = None):
    if api_key is None:
        credential = credential_service.get_credential_by_provider_name(db, provider_name="groq", company_id=company_id)
        if not credential:
            raise ValueError("Groq API key not found for this company.")
        api_key = credential.api_key

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

            if response_message.tool_calls:
                tool_call = response_message.tool_calls[0]
                tool_name = tool_call.function.name
                
                # Pre-execution validation
                available_tool_names = [tool['function']['name'] for tool in tools]
                if tool_name not in available_tool_names:
                    error_message = f"You tried to call a tool named '{tool_name}', but that tool does not exist. Please choose a tool from the following available list: {', '.join(available_tool_names)}. Or, ask the user for clarification."
                    
                    # Add the error to the history and retry
                    messages.append(response_message) # Add the LLM's failed attempt
                    messages.append({"role": "system", "content": error_message}) # Add our corrective prompt
                    
                    print(f"DEBUG: Invalid tool '{tool_name}'. Retrying... (Attempt {attempt + 1}/{max_retries})")
                    continue # Go to the next iteration of the loop to retry

                return {
                    "type": "tool_call",
                    "tool_call_id": tool_call.id,
                    "tool_name": tool_name,
                    "parameters": json.loads(tool_call.function.arguments)
                }
            else:
                return {
                    "type": "text",
                    "content": response_message.content
                }

        except Exception as e:
            print(f"Groq API Error: {e}")
            # If there's an API error, we break the loop and return the error.
            return {
                "type": "text",
                "content": f"An error occurred with the LLM provider: {e}"
            }

    # If all retries fail, return a final error message
    return {
        "type": "text",
        "content": "I am having trouble selecting the correct tool. Could you please rephrase your request?"
    }