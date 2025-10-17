
from groq import Groq
from app.llm_providers.groq_provider import generate_response as groq_generate_response
from app.services import credential_service
from app.services.vault_service import vault_service

def execute_ai_tool(db, user, tool, answers, language, api_key=None):
    if api_key is None:
        credential = credential_service.get_credential_by_service_name(db, service_name="groq", company_id=user.company_id)
        if not credential:
            raise ValueError("Groq API key not found for this company.")
        api_key =   vault_service.decrypt(credential.encrypted_credentials)

    client = Groq(api_key=api_key)
    # Create a prompt from the tool and answers
    prompt = f"You are an expert in {tool.category.name}. "
    prompt += f"You are using the tool \"{tool.name}\". "
    prompt += f"The user has provided the following information:\n"
    for question in tool.questions:
        prompt += f"- {question.question_text}: {answers.get(str(question.id), 'N/A')}\n"
    prompt += f"Please provide a response in {language}."

    # Call the LLM
    model_name = "llama-3.1-8b-instant" # Hardcoded Groq model name
    chat_history = []

    response = groq_generate_response(
        db=db,
        company_id=user.company_id,
        model_name=model_name,
        system_prompt=prompt,
        chat_history=chat_history,
        tools=None,
        api_key=api_key
    )

    return response["content"] if response["type"] == "text" else "An error occurred with the LLM provider."
