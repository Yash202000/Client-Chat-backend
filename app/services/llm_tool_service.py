
from app.llm_providers.gemini_provider import generate_response as ggr
from app.llm_providers.groq_provider import generate_response as grg
from app.services import knowledge_base_service
from sqlalchemy.orm import Session
from app.models.tool import Tool

class LLMToolService:
    def __init__(self, db: Session):
        self.db = db

    def execute(self, model: str, system_prompt: str, chat_history: list, user_prompt: str, company_id: int, tools: list[Tool], knowledge_base_id: int = None):
        augmented_prompt = user_prompt

        if knowledge_base_id:
            relevant_chunks = knowledge_base_service.find_relevant_chunks(
                self.db, knowledge_base_id, company_id, user_prompt
            )
            if relevant_chunks:
                context = "\n\nContext:\n" + "\n".join(relevant_chunks)
                augmented_prompt = f"{user_prompt}{context}"
                print(f"DEBUG: Augmented prompt with KB context: {augmented_prompt}")
            else:
                print("DEBUG: No relevant chunks found for the prompt.")

        full_chat_history = chat_history + [{"role": "user", "content": augmented_prompt}]

        # Format the tools for the LLM provider
        formatted_tools = []
        for tool in tools:
            if tool.parameters and isinstance(tool.parameters, dict):
                formatted_tools.append({
                    "type": "function",
                    "function": {
                        "name": tool.name.replace(" ", "_"),
                        "description": tool.description,
                        "parameters": tool.parameters,
                    },
                })

        provider, model_name = model.split('/')
        
        if provider == "gemini":
            response = ggr(db=self.db, company_id=company_id, model_name=model_name, system_prompt=system_prompt, chat_history=full_chat_history, tools=formatted_tools)
            return response
        elif provider == "groq":
            response = grg(db=self.db, company_id=company_id, model_name=model_name, system_prompt=system_prompt, chat_history=full_chat_history, tools=formatted_tools)
            return response
        else:
            return {"error": f"Unsupported LLM provider: {provider}"}
