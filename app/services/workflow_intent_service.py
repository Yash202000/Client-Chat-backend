from typing import List, Dict, Optional, Tuple
from sqlalchemy.orm import Session
import re
from datetime import datetime
from app.models.workflow import Workflow
from app.models.intent import Intent, IntentMatch
from app.services.intent_service import generate_llm_response


class WorkflowIntentService:
    """
    Service for handling workflow-specific intent detection.
    Uses intent_config from the workflow instead of global intents.
    """

    def __init__(self, db: Session):
        self.db = db

    def workflow_has_intents_enabled(self, workflow: Workflow) -> bool:
        """Check if workflow has intent detection enabled"""
        if not workflow.intent_config:
            return False
        return workflow.intent_config.get("enabled", False)

    async def detect_intent_for_workflow(
        self,
        message: str,
        workflow: Workflow,
        conversation_id: str,
        company_id: int
    ) -> Optional[Tuple[Dict, float, Dict[str, any], str]]:
        """
        Detect intent using workflow's configured intents.

        Returns: (intent_dict, confidence_score, extracted_entities, matched_method)
        """

        if not self.workflow_has_intents_enabled(workflow):
            print(f"Intent detection not enabled for workflow {workflow.id}")
            return None

        trigger_intents = workflow.intent_config.get("trigger_intents", [])
        if not trigger_intents:
            print(f"No trigger intents configured for workflow {workflow.id}")
            return None

        print(f"Checking message against {len(trigger_intents)} workflow intents...")

        # Stage 1: Keyword matching (very fast)
        keyword_match = self._keyword_match(message, trigger_intents)
        if keyword_match and keyword_match[1] >= 0.9:  # High confidence (90%+)
            print(f"✓ Keyword match: {keyword_match[0]['name']} ({keyword_match[1]:.2f})")
            return await self._finalize_intent_match(
                keyword_match[0], message, conversation_id, keyword_match[1], "keyword", workflow, company_id
            )

        # Stage 2: Phrase similarity (medium speed)
        phrase_match = self._phrase_similarity_match(message, trigger_intents)
        if phrase_match and phrase_match[1] >= 0.8:  # Good confidence (80%+)
            print(f"✓ Phrase similarity match: {phrase_match[0]['name']} ({phrase_match[1]:.2f})")
            return await self._finalize_intent_match(
                phrase_match[0], message, conversation_id, phrase_match[1], "similarity", workflow, company_id
            )

        # Stage 3: LLM classification (accurate but slower)
        llm_match = await self._llm_classify_intent(message, trigger_intents)
        if llm_match:
            intent_dict, confidence = llm_match
            intent_threshold = intent_dict.get("confidence_threshold", 0.7)
            if confidence >= intent_threshold:
                print(f"✓ LLM match: {intent_dict['name']} ({confidence:.2f})")
                return await self._finalize_intent_match(
                    intent_dict, message, conversation_id, confidence, "llm", workflow, company_id
                )

        print(f"✗ No workflow intent matched for message: '{message[:50]}...'")
        return None

    def _keyword_match(self, message: str, intents: List[Dict]) -> Optional[Tuple[Dict, float]]:
        """Fast keyword matching - Stage 1"""
        message_lower = message.lower()
        best_match = None
        best_score = 0.0

        for intent_dict in intents:
            keywords = intent_dict.get("keywords", [])
            if not keywords:
                continue

            matched_keywords = sum(1 for kw in keywords if kw.lower() in message_lower)

            if len(keywords) == 0:
                continue

            score = matched_keywords / len(keywords)

            if score > best_score:
                best_score = score
                best_match = intent_dict

        return (best_match, best_score) if best_match and best_score > 0 else None

    def _phrase_similarity_match(self, message: str, intents: List[Dict]) -> Optional[Tuple[Dict, float]]:
        """Phrase similarity using string matching - Stage 2"""
        message_lower = message.lower()
        best_match = None
        best_score = 0.0

        for intent_dict in intents:
            training_phrases = intent_dict.get("training_phrases", [])
            if not training_phrases:
                continue

            for phrase in training_phrases:
                phrase_lower = phrase.lower()

                # Exact match
                if phrase_lower == message_lower:
                    return (intent_dict, 1.0)

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
                    best_match = intent_dict

        return (best_match, best_score) if best_match and best_score > 0.5 else None

    async def _llm_classify_intent(self, message: str, intents: List[Dict]) -> Optional[Tuple[Dict, float]]:
        """Use LLM to classify intent - Stage 3"""

        # Build prompt with available intents
        intent_descriptions = "\n".join([
            f"- {intent.get('name')}: {intent.get('description', 'No description')}"
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
                matched_intent = next((i for i in intents if i.get("name") == intent_name), None)
                if matched_intent:
                    return (matched_intent, confidence)

        except Exception as e:
            print(f"Error in LLM intent classification: {e}")

        return None

    async def _finalize_intent_match(
        self,
        intent_dict: Dict,
        message: str,
        conversation_id: str,
        confidence: float,
        matched_method: str,
        workflow: Workflow,
        company_id: int
    ) -> Tuple[Dict, float, Dict[str, any], str]:
        """Finalize intent match, extract entities, and record the match"""

        # Extract entities for this workflow
        entities = await self.extract_workflow_entities(message, workflow, intent_dict)

        # Record the match in database (for analytics)
        # We create a temporary Intent-like record for tracking
        intent_match = IntentMatch(
            conversation_id=conversation_id,
            intent_id=None,  # No global intent ID, this is workflow-specific
            message_text=message,
            confidence_score=confidence,
            matched_method=matched_method,
            extracted_entities=entities,
            triggered_workflow_id=workflow.id,
            workflow_executed=False,  # Will be updated after workflow execution
            matched_at=datetime.now()
        )
        self.db.add(intent_match)
        self.db.commit()

        return (intent_dict, confidence, entities, matched_method)

    async def extract_workflow_entities(
        self,
        message: str,
        workflow: Workflow,
        intent_dict: Optional[Dict] = None
    ) -> Dict[str, any]:
        """Extract entities defined in workflow's intent_config"""

        if not workflow.intent_config:
            return {}

        entity_configs = workflow.intent_config.get("entities", [])
        if not entity_configs:
            return {}

        extracted = {}

        for entity_config in entity_configs:
            entity_name = entity_config.get("name")
            extraction_method = entity_config.get("extraction_method", "llm")
            validation_regex = entity_config.get("validation_regex")

            if extraction_method == "regex" and validation_regex:
                # Regex extraction
                try:
                    match = re.search(validation_regex, message)
                    if match:
                        extracted[entity_name] = match.group(0)
                        print(f"✓ Extracted entity '{entity_name}': {match.group(0)} (regex)")
                except Exception as e:
                    print(f"Regex extraction error for {entity_name}: {e}")

            elif extraction_method == "llm":
                # LLM extraction
                value = await self._llm_extract_entity(message, entity_config)
                if value:
                    extracted[entity_name] = value
                    print(f"✓ Extracted entity '{entity_name}': {value} (llm)")

        return extracted

    async def _llm_extract_entity(self, message: str, entity_config: Dict) -> Optional[str]:
        """Use LLM to extract entity value"""

        entity_name = entity_config.get("name")
        entity_type = entity_config.get("type", "text")
        description = entity_config.get("description", "")
        example_values = entity_config.get("example_values", [])

        prompt = f"""Extract the {entity_name} ({entity_type}) from this message.

Message: "{message}"

{f'Description: {description}' if description else ''}
Entity type: {entity_type}
{f'Example values: {", ".join(example_values[:3])}' if example_values else ''}

If the {entity_name} is found in the message, respond with ONLY the extracted value.
If not found, respond with exactly: NOT_FOUND

Response (just the value or NOT_FOUND):"""

        try:
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
            print(f"Error extracting entity {entity_name}: {e}")
            return None

    def update_intent_match_execution_status(
        self,
        conversation_id: str,
        workflow_id: int,
        workflow_executed: bool,
        execution_status: str
    ):
        """Update the execution status of the most recent workflow intent match"""

        intent_match = self.db.query(IntentMatch).filter(
            IntentMatch.conversation_id == conversation_id,
            IntentMatch.triggered_workflow_id == workflow_id
        ).order_by(IntentMatch.matched_at.desc()).first()

        if intent_match:
            intent_match.workflow_executed = workflow_executed
            intent_match.execution_status = execution_status
            self.db.commit()

    def should_auto_trigger(self, workflow: Workflow, confidence: float) -> bool:
        """Check if workflow should auto-trigger based on confidence"""

        if not workflow.intent_config:
            return False

        auto_trigger_enabled = workflow.intent_config.get("auto_trigger_enabled", False)
        if not auto_trigger_enabled:
            return False

        min_confidence = workflow.intent_config.get("min_confidence", 0.7)
        return confidence >= min_confidence
