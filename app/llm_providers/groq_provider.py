from groq import Groq
from app.core.config import settings
import json

def generate_response(api_key: str, model_name: str, system_prompt: str, chat_history: list, tools: list):
    """
    Generates a response using the Groq API with a provided API key.
    """
    if not api_key:
        raise ValueError("GROQ_API_KEY is not configured for this agent.")

    client = Groq(api_key=api_key)

    # Format messages for Groq API
    messages = [{"role": "system", "content": system_prompt}]
    for msg in chat_history:
        role = "user" if msg.sender == "user" else "assistant"
        messages.append({"role": role, "content": msg.message})

    # Format tools for Groq API
    groq_tools = []
    if tools:
        for tool in tools:
            groq_tools.append({
                "type": "function",
                "function": {
                    "name": tool['name'],
                    "description": tool['description'],
                    "parameters": tool['parameters']
                }
            })

    chat_completion = client.chat.completions.create(
        messages=messages,
        model=model_name,
        tools=groq_tools if groq_tools else None,
        tool_choice="auto"
    )

    response_message = chat_completion.choices[0].message
    
    if response_message.tool_calls:
        tool_call = response_message.tool_calls[0]
        try:
            # Use json.loads for safe and reliable parsing
            arguments = json.loads(tool_call.function.arguments)
        except json.JSONDecodeError:
            arguments = {} # Handle cases where arguments are not valid JSON

        return {
            "type": "tool_call",
            "tool_name": tool_call.function.name,
            "parameters": arguments
        }

    return {"type": "text", "content": response_message.content}
