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
    # The chat_history is already formatted as a list of dicts with 'role' and 'content'
    messages.extend(chat_history)

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
            return {
                "type": "tool_call",
                "tool_name": tool_call.function.name,
                "parameters": json.loads(tool_call.function.arguments)
            }
        else:
            return {
                "type": "text",
                "content": response_message.content
            }

    except Exception as e:
        print(f"Groq API Error: {e}")
        return {
            "type": "text",
            "content": f"An error occurred with the LLM provider: {e}"
        }