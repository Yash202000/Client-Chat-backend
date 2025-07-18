from app.llm_providers.groq_provider import generate_response

async def get_suggested_replies(conversation_history: list[str]) -> list[str]:
    """
    Generates a list of suggested replies based on the conversation history.
    """

    prompt = f"Based on the following conversation, please provide a list of 3 suggested replies for the agent:\n\n{""}".join(conversation_history)
    
    response = await generate_response(chat_history=prompt)
    return response.split('\n')
