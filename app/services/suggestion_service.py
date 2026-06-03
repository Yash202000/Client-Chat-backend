from app.llm_providers.groq_provider import generate_response
from sqlalchemy.orm import Session

async def get_suggested_replies(db: Session, company_id: int, conversation_history: list[str]) -> list[str]:
    """
    Generates a list of suggested replies based on the conversation history.
    """
    history_text = "\n".join(conversation_history)
    prompt = (
        "You are a helpful customer support assistant. "
        "Based on the conversation below, provide exactly 3 short, natural reply suggestions for the agent. "
        "Return only the replies, one per line, with no numbering, bullets, or extra explanation.\n\n"
        f"Conversation:\n{history_text}"
    )

    response = await generate_response(
        db=db,
        company_id=company_id,
        model_name="mixtral-8x7b-32768",
        system_prompt="You are a concise customer support reply assistant.",
        chat_history=[{"role": "user", "content": prompt}],
    )
    lines = [line.strip() for line in response["content"].split('\n') if line.strip()]
    return lines[:3]
