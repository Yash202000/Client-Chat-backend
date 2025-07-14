import google.generativeai as genai

def generate_response(api_key: str, model_name: str, system_prompt: str, chat_history: list, tools: list):
    """
    Generates a response using the Gemini API with a provided API key.
    """
    if not api_key:
        raise ValueError("GOOGLE_API_KEY is not configured for this agent.")
    
    genai.configure(api_key=api_key)

    model = genai.GenerativeModel(
        model_name=model_name,
        system_instruction=system_prompt,
        tools=tools if tools else None
    )

    gemini_history = []
    for msg in chat_history:
        role = 'user' if msg.sender == 'user' else 'model'
        gemini_history.append({"role": role, "parts": [{"text": msg.message}]})

    user_prompt = gemini_history.pop(-1)['parts'][0]['text']

    model_chat_session = model.start_chat(history=gemini_history)
    response = model_chat_session.send_message(user_prompt)

    try:
        function_call = response.candidates[0].content.parts[0].function_call
        if function_call:
            return {
                "type": "tool_call",
                "tool_name": function_call.name,
                "parameters": {key: value for key, value in function_call.args.items()}
            }
    except (ValueError, AttributeError, IndexError):
        pass

    return {"type": "text", "content": response.text}