
from app.llm_providers.gemini_provider import generate_response as ggr
from app.llm_providers.groq_provider import generate_response as grg
from app.services import knowledge_base_service # Import knowledge_base_service
from sqlalchemy.orm import Session # Import Session for type hinting

class LLMToolService:
    def __init__(self, db: Session):
        self.db = db

    def execute(self, model: str, prompt: str, knowledge_base_id: int = None, company_id: int = None):
        augmented_prompt = prompt

        if knowledge_base_id and company_id:
            # Retrieve relevant chunks from the knowledge base
            relevant_chunks = knowledge_base_service.find_relevant_chunks(
                self.db, knowledge_base_id, company_id, prompt
            )
            if relevant_chunks:
                context = "\n\nContext:\n" + "\n".join(relevant_chunks)
                augmented_prompt = f"{prompt}{context}"
                print(f"DEBUG: Augmented prompt with KB context: {augmented_prompt}")
            else:
                print("DEBUG: No relevant chunks found for the prompt.")

        if model.startswith("gemini"): # Assuming Gemini models start with "gemini"
            response = ggr(augmented_prompt)
            return response
        elif model.startswith("groq"): # Assuming Groq models start with "groq"
            response = grg(augmented_prompt)
            return response
        else:
            return {"error": f"Unsupported LLM model: {model}"}
