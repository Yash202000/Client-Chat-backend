from groq import Groq
import json

def generate_response(api_key: str, model_name: str, system_prompt: str, chat_history: list, tools: list = None):
    """
    Generates a response from the Groq API, handling chat history and potential tool calls.
    """
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