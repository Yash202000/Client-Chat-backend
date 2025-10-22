from typing import List, Dict, Optional, Tuple
from sqlalchemy.orm import Session
import re
from datetime import datetime
from app.models.intent import Intent, IntentMatch, Entity, intent_entities
from app.models.workflow import Workflow


class IntentService:
    """Service for intent detection and entity extraction"""

    def __init__(self, db: Session):
        self.db = db

    async def detect_intent(
        self,
        message: str,
        company_id: int,
        conversation_id: str
    ) -> Optional[Tuple[Intent, float, Dict[str, any], str]]:
        """
        Detect intent using multi-stage approach:
        1. Keyword matching (fast, ~10ms)
        2. Phrase similarity (medium, ~50ms)
        3. LLM classification (accurate but slower, ~500ms)

        Returns: (Intent, confidence_score, extracted_entities, matched_method)
        """

        # Get all active intents for company, ordered by priority
        intents = self.db.query(Intent).filter(
            Intent.company_id == company_id,
            Intent.is_active == True
        ).order_by(Intent.priority.desc()).all()

        if not intents:
            print(f"No active intents found for company {company_id}")
            return None

        print(f"Checking message against {len(intents)} intents...")

        # Stage 1: Keyword matching (very fast)
        keyword_match = self._keyword_match(message, intents)
        if keyword_match and keyword_match[1] >= 0.9:  # High confidence (90%+)
            print(f"✓ Keyword match: {keyword_match[0].name} ({keyword_match[1]:.2f})")
            return await self._finalize_intent_match(
                keyword_match[0], message, conversation_id, keyword_match[1], "keyword"
            )

        # Stage 2: Phrase similarity (medium speed)
        phrase_match = self._phrase_similarity_match(message, intents)
        if phrase_match and phrase_match[1] >= 0.8:  # Good confidence (80%+)
            print(f"✓ Phrase similarity match: {phrase_match[0].name} ({phrase_match[1]:.2f})")
            return await self._finalize_intent_match(
                phrase_match[0], message, conversation_id, phrase_match[1], "similarity"
            )

        # Stage 3: LLM classification (accurate but slower)
        llm_match = await self._llm_classify_intent(message, intents)
        if llm_match and llm_match[1] >= llm_match[0].confidence_threshold:
            print(f"✓ LLM match: {llm_match[0].name} ({llm_match[1]:.2f})")
            return await self._finalize_intent_match(
                llm_match[0], message, conversation_id, llm_match[1], "llm"
            )

        print(f"✗ No intent matched for message: '{message[:50]}...'")
        return None

    def _keyword_match(self, message: str, intents: List[Intent]) -> Optional[Tuple[Intent, float]]:
        """Fast keyword matching - Stage 1"""
        message_lower = message.lower()
        best_match = None
        best_score = 0.0

        for intent in intents:
            if not intent.keywords:
                continue

            keywords = intent.keywords
            matched_keywords = sum(1 for kw in keywords if kw.lower() in message_lower)

            if len(keywords) == 0:
                continue

            score = matched_keywords / len(keywords)

            if score > best_score:
                best_score = score
                best_match = intent

        return (best_match, best_score) if best_match and best_score > 0 else None

    def _phrase_similarity_match(self, message: str, intents: List[Intent]) -> Optional[Tuple[Intent, float]]:
        """Phrase similarity using string matching - Stage 2"""
        message_lower = message.lower()
        best_match = None
        best_score = 0.0

        for intent in intents:
            if not intent.training_phrases:
                continue

            for phrase in intent.training_phrases:
                phrase_lower = phrase.lower()

                # Exact match
                if phrase_lower == message_lower:
                    return (intent, 1.0)

                # Phrase contained in message or vice versa
                if phrase_lower in message_lower:
                    score = 0.9
                elif message_lower in phrase_lower:
                    score = 0.85
                else:
                    # Calculate word overlap
                    message_words = set(message_lower.split())
                    phrase_words = set(phrase_lower.split())

                    if len(phrase_words) == 0:
                        continue

                    overlap = len(message_words & phrase_words)
                    score = overlap / len(phrase_words)

                if score > best_score:
                    best_score = score
                    best_match = intent

        return (best_match, best_score) if best_match and best_score > 0.5 else None

    async def _llm_classify_intent(self, message: str, intents: List[Intent]) -> Optional[Tuple[Intent, float]]:
        """Use LLM to classify intent - Stage 3"""

        # Build prompt with available intents
        intent_descriptions = "\n".join([
            f"- {intent.name}: {intent.description or 'No description'}"
            for intent in intents
        ])

        prompt = f"""You are an intent classifier. Analyze the user message and determine which intent it matches.

Available intents:
{intent_descriptions}

User message: "{message}"

Respond with JSON in this exact format (no markdown, just raw JSON):
{{
    "intent_name": "the matching intent name or null if no match",
    "confidence": 0.0-1.0,
    "reasoning": "brief explanation"
}}"""

        try:
            # Import here to avoid circular dependency
            from app.services.agent_execution_service import generate_llm_response

            response = await generate_llm_response(
                prompt=prompt,
                temperature=0.1,
                max_tokens=200
            )

            # Parse JSON response
            import json

            # Clean response (remove markdown code blocks if present)
            cleaned_response = response.strip()
            if cleaned_response.startswith('```'):
                cleaned_response = cleaned_response.split('```')[1]
                if cleaned_response.startswith('json'):
                    cleaned_response = cleaned_response[4:]

            result = json.loads(cleaned_response.strip())
            intent_name = result.get("intent_name")
            confidence = float(result.get("confidence", 0.0))

            if intent_name and intent_name != "null":
                matched_intent = next((i for i in intents if i.name == intent_name), None)
                if matched_intent:
                    return (matched_intent, confidence)

        except Exception as e:
            print(f"Error in LLM intent classification: {e}")

        return None

    async def _finalize_intent_match(
        self,
        intent: Intent,
        message: str,
        conversation_id: str,
        confidence: float,
        matched_method: str
    ) -> Tuple[Intent, float, Dict[str, any], str]:
        """Finalize intent match, extract entities, and record the match"""

        # Extract entities for this intent
        entities = await self.extract_entities(message, intent)

        # Record the match in database
        intent_match = IntentMatch(
            conversation_id=conversation_id,
            intent_id=intent.id,
            message_text=message,
            confidence_score=confidence,
            matched_method=matched_method,
            extracted_entities=entities,
            triggered_workflow_id=intent.trigger_workflow_id,
            workflow_executed=False,  # Will be updated after workflow execution
            matched_at=datetime.now()
        )
        self.db.add(intent_match)
        self.db.commit()

        return (intent, confidence, entities, matched_method)

    async def extract_entities(self, message: str, intent: Intent) -> Dict[str, any]:
        """Extract entities from message based on intent requirements"""

        # Get entities associated with this intent
        entities = self.db.query(Entity).join(
            intent_entities
        ).filter(
            intent_entities.c.intent_id == intent.id,
            Entity.is_active == True
        ).all()

        if not entities:
            return {}

        extracted = {}

        for entity in entities:
            if entity.extraction_method == "regex" and entity.validation_regex:
                # Regex extraction
                try:
                    match = re.search(entity.validation_regex, message)
                    if match:
                        extracted[entity.name] = match.group(0)
                        print(f"✓ Extracted entity '{entity.name}': {match.group(0)} (regex)")
                except Exception as e:
                    print(f"Regex extraction error for {entity.name}: {e}")

            elif entity.extraction_method == "llm":
                # LLM extraction
                value = await self._llm_extract_entity(message, entity)
                if value:
                    extracted[entity.name] = value
                    print(f"✓ Extracted entity '{entity.name}': {value} (llm)")

        return extracted

    async def _llm_extract_entity(self, message: str, entity: Entity) -> Optional[str]:
        """Use LLM to extract entity value"""

        prompt = f"""Extract the {entity.name} ({entity.entity_type}) from this message.

Message: "{message}"

Entity description: {entity.description or 'No description'}
Entity type: {entity.entity_type}
{f'Example values: {", ".join(entity.example_values[:3])}' if entity.example_values else ''}

If the {entity.name} is found in the message, respond with ONLY the extracted value.
If not found, respond with exactly: NOT_FOUND

Response (just the value or NOT_FOUND):"""

        try:
            from app.services.agent_execution_service import generate_llm_response

            response = await generate_llm_response(
                prompt=prompt,
                temperature=0.1,
                max_tokens=100
            )

            response = response.strip()
            if response == "NOT_FOUND" or response.lower() == "not_found":
                return None

            return response

        except Exception as e:
            print(f"Error extracting entity {entity.name}: {e}")
            return None

    def update_intent_match_execution_status(
        self,
        conversation_id: str,
        intent_id: int,
        workflow_executed: bool,
        execution_status: str
    ):
        """Update the execution status of the most recent intent match"""

        intent_match = self.db.query(IntentMatch).filter(
            IntentMatch.conversation_id == conversation_id,
            IntentMatch.intent_id == intent_id
        ).order_by(IntentMatch.matched_at.desc()).first()

        if intent_match:
            intent_match.workflow_executed = workflow_executed
            intent_match.execution_status = execution_status
            self.db.commit()


# Helper function to check if LLM service is available
async def generate_llm_response(prompt: str, temperature: float = 0.1, max_tokens: int = 500) -> str:
    """
    Generate LLM response using the default agent's LLM provider.
    This is a simplified version - you should adapt it to use your existing LLM service.
    """
    try:
        # Import your existing LLM generation logic
        from app.services.llm_providers.groq_provider import GroqProvider
        from app.core.config import settings

        # Use Groq as default for intent classification (fast and cheap)
        provider = GroqProvider(api_key=settings.GROQ_API_KEY)

        response = await provider.generate_completion(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=max_tokens
        )

        return response

    except Exception as e:
        print(f"Error generating LLM response: {e}")
        return ""
