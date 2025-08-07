from sqlalchemy.orm import Session
from app.models import optimization_suggestion as models_optimization_suggestion
from app.schemas import optimization_suggestion as schemas_optimization_suggestion
from app.models import chat_message as models_chat_message
from app.llm_providers.groq_provider import generate_response as groq_generate_response
from app.llm_providers.gemini_provider import generate_response as gemini_generate_response
import random

def create_optimization_suggestion(db: Session, suggestion: schemas_optimization_suggestion.OptimizationSuggestionCreate, company_id: int):
    db_suggestion = models_optimization_suggestion.OptimizationSuggestion(
        **suggestion.dict(),
        company_id=company_id
    )
    db.add(db_suggestion)
    db.commit()
    db.refresh(db_suggestion)
    return db_suggestion

def get_optimization_suggestions(db: Session, company_id: int, skip: int = 0, limit: int = 100):
    return db.query(models_optimization_suggestion.OptimizationSuggestion).filter(models_optimization_suggestion.OptimizationSuggestion.company_id == company_id).offset(skip).limit(limit).all()

async def generate_suggestions_from_llm(db: Session, company_id: int, agent_id: int = None):
    # Placeholder for actual LLM-powered analysis
    # In a real scenario, this would involve:
    # 1. Fetching recent chat messages for the company/agent.
    # 2. Analyzing them for patterns (e.g., frequent escalations, unanswered questions).
    # 3. Using an LLM to generate concrete suggestions.

    # For demonstration, return random suggestions
    suggestion_types = [
        "prompt_refinement",
        "knowledge_base_gap",
        "new_tool_recommendation",
        "conversation_flow_improvement"
    ]
    descriptions = [
        "Consider refining the agent's initial greeting to be more engaging.",
        "Add more information about product returns to the knowledge base.",
        "Integrate a new tool for order tracking to reduce manual lookups.",
        "Simplify the conversation flow for common customer inquiries."
    ]

    suggestions = []
    for _ in range(random.randint(1, 3)): # Generate 1-3 random suggestions
        s_type = random.choice(suggestion_types)
        desc = random.choice(descriptions)
        suggestion_data = schemas_optimization_suggestion.OptimizationSuggestionCreate(
            suggestion_type=s_type,
            description=desc,
            agent_id=agent_id,
            details={"example_detail": "This is a placeholder detail."}
        )
        suggestions.append(create_optimization_suggestion(db, suggestion_data, company_id))
    return suggestions
