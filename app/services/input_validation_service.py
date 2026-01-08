"""
Input Validation Service for Workflow Nodes

Provides multi-stage validation for prompt and listen nodes:
- Exact: Fast string matching
- Fuzzy: Levenshtein similarity matching
- LLM: Semantic matching using configurable LLM providers
"""

from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import json
from difflib import SequenceMatcher
from sqlalchemy.orm import Session

from app.services.prompt_guard_service import prompt_guard
from app.services import credential_service
from app.services.vault_service import vault_service


class ValidationMode(Enum):
    """Validation strictness modes"""
    NONE = "none"      # No validation, accept any input
    EXACT = "exact"    # Exact string match only
    FUZZY = "fuzzy"    # Exact + fuzzy string similarity
    LLM = "llm"        # Exact + fuzzy + LLM semantic matching


@dataclass
class ValidationResult:
    """Result of input validation"""
    is_valid: bool
    matched_option_key: Optional[str] = None  # For prompt nodes - the matched option
    confidence: float = 1.0
    reason: str = ""
    hint_message: str = ""  # Message to show user on re-ask
    extracted_value: Optional[str] = None  # For listen nodes - extracted entity value from LLM


class InputValidationService:
    """Service for LLM-powered validation of user input in workflow nodes."""

    def __init__(self):
        pass

    def _sanitize_user_input(self, text: str) -> str:
        """
        Sanitize user input using the existing PromptGuardService.
        Protects against prompt injection attacks.
        """
        if not text:
            return ""
        scan_result = prompt_guard.scan_message(text, check_off_topic=False)
        return scan_result.sanitized_message

    async def validate_prompt_response(
        self,
        db: Session,
        company_id: int,
        user_input: str,
        options: List[Dict],
        allow_text_input: bool,
        prompt_context: str,
        validation_mode: ValidationMode = ValidationMode.EXACT,
        llm_provider: str = "groq",
        llm_model: str = None
    ) -> ValidationResult:
        """
        Validate user response against prompt options.

        Args:
            db: Database session for credential lookup
            company_id: Company ID for credential lookup
            user_input: The user's response text
            options: List of {key: str, value: str} option pairs
            allow_text_input: Whether free text is allowed
            prompt_context: The original question text for context
            validation_mode: How strictly to validate
            llm_provider: LLM provider - "groq", "openai", or "google"
            llm_model: Model name (uses provider default if not specified)

        Returns:
            ValidationResult with is_valid, matched_option_key, hint_message
        """
        if not user_input or not user_input.strip():
            return ValidationResult(
                is_valid=False,
                reason="Empty input",
                hint_message="Please provide a response."
            )

        # If text input is allowed and no options, accept anything
        if allow_text_input and not options:
            return ValidationResult(is_valid=True, matched_option_key=user_input)

        # No validation mode - accept anything
        if validation_mode == ValidationMode.NONE:
            return ValidationResult(is_valid=True, matched_option_key=user_input)

        user_input_clean = user_input.strip()

        # Stage 1: Exact match (always try this first)
        exact_match = self._exact_match_options(user_input_clean, options)
        if exact_match:
            return ValidationResult(
                is_valid=True,
                matched_option_key=exact_match,
                confidence=1.0,
                reason="Exact match"
            )

        # If exact mode, no fuzzy/LLM fallback
        if validation_mode == ValidationMode.EXACT:
            if allow_text_input:
                return ValidationResult(is_valid=True, matched_option_key=user_input_clean)
            return ValidationResult(
                is_valid=False,
                reason="No exact match found",
                hint_message=self._generate_options_hint(options)
            )

        # Stage 2: Fuzzy match (for FUZZY and LLM modes)
        if validation_mode in [ValidationMode.FUZZY, ValidationMode.LLM]:
            fuzzy_result = self._fuzzy_match_options(user_input_clean, options, threshold=0.7)
            if fuzzy_result:
                matched_key, confidence = fuzzy_result
                return ValidationResult(
                    is_valid=True,
                    matched_option_key=matched_key,
                    confidence=confidence,
                    reason="Fuzzy match"
                )

        # If fuzzy mode and no match, fail or accept text
        if validation_mode == ValidationMode.FUZZY:
            if allow_text_input:
                return ValidationResult(is_valid=True, matched_option_key=user_input_clean)
            return ValidationResult(
                is_valid=False,
                reason="No similar option found",
                hint_message=self._generate_options_hint(options)
            )

        # Stage 3: LLM semantic match (only for LLM mode)
        if validation_mode == ValidationMode.LLM:
            llm_result = await self._llm_match_options(db, company_id, user_input_clean, options, prompt_context, llm_provider, llm_model)
            if llm_result:
                matched_key, confidence, reasoning = llm_result
                return ValidationResult(
                    is_valid=True,
                    matched_option_key=matched_key,
                    confidence=confidence,
                    reason=f"LLM match: {reasoning}"
                )

            # LLM couldn't match any option - always check relevance
            # Even with allow_text_input, we should reject completely unrelated inputs
            relevance = await self._llm_check_relevance(db, company_id, user_input_clean, prompt_context, options, llm_provider, llm_model)
            if not relevance[0]:
                # Off-topic/unrelated response - reject regardless of allow_text_input
                return ValidationResult(
                    is_valid=False,
                    reason="Off-topic response",
                    hint_message=relevance[2] or self._generate_options_hint(options)
                )

            # On-topic but no exact option match
            if allow_text_input:
                # Accept free text only if it's relevant to the question
                return ValidationResult(is_valid=True, matched_option_key=user_input_clean)

            return ValidationResult(
                is_valid=False,
                reason="No matching option",
                hint_message=self._generate_options_hint(options)
            )

        # Fallback
        if allow_text_input:
            return ValidationResult(is_valid=True, matched_option_key=user_input_clean)

        return ValidationResult(
            is_valid=False,
            reason="Validation failed",
            hint_message=self._generate_options_hint(options)
        )

    async def validate_listen_response(
        self,
        db: Session,
        company_id: int,
        user_input: str,
        question_text: str,
        expected_input_type: str = "any",
        validation_mode: ValidationMode = ValidationMode.NONE,
        llm_provider: str = "groq",
        llm_model: str = None
    ) -> ValidationResult:
        """
        Validate user response for listen node.

        Args:
            db: Database session for credential lookup
            company_id: Company ID for credential lookup
            user_input: The user's response text
            question_text: The question context (explicit or from previous message)
            expected_input_type: "any", "text", "attachment", "location"
            validation_mode: How strictly to validate
            llm_provider: LLM provider - "groq", "openai", or "google"
            llm_model: Model name (uses provider default if not specified)

        Returns:
            ValidationResult with is_valid, reason, hint_message
        """
        if not user_input or not user_input.strip():
            return ValidationResult(
                is_valid=False,
                reason="Empty input",
                hint_message="Please provide a response."
            )

        # No validation mode - accept anything
        if validation_mode == ValidationMode.NONE:
            return ValidationResult(is_valid=True)

        user_input_clean = user_input.strip()

        # Exact mode - just basic type validation
        if validation_mode == ValidationMode.EXACT:
            return ValidationResult(is_valid=True)

        # Fuzzy mode - basic relevance check without LLM
        if validation_mode == ValidationMode.FUZZY:
            # Check if response is too short (likely not meaningful)
            if len(user_input_clean) < 2:
                return ValidationResult(
                    is_valid=False,
                    reason="Response too short",
                    hint_message="Please provide a more detailed response."
                )

            # Check if it looks like a question (off-topic)
            if user_input_clean.endswith('?') and question_text:
                return ValidationResult(
                    is_valid=False,
                    reason="Appears to be a question instead of an answer",
                    hint_message=f"Please answer: {question_text}"
                )

            return ValidationResult(is_valid=True)

        # LLM mode - full semantic validation with entity extraction
        if validation_mode == ValidationMode.LLM:
            if not question_text:
                # No context to validate against
                return ValidationResult(is_valid=True)

            is_valid, reason, hint, extracted_value = await self._llm_validate_relevance(
                db, company_id, user_input_clean, question_text, expected_input_type, llm_provider, llm_model
            )

            return ValidationResult(
                is_valid=is_valid,
                reason=reason,
                hint_message=hint,
                extracted_value=extracted_value
            )

        return ValidationResult(is_valid=True)

    def _exact_match_options(
        self,
        user_input: str,
        options: List[Dict]
    ) -> Optional[str]:
        """
        Fast path: exact string match against option keys/values.

        Returns: matched option key or None
        """
        user_lower = user_input.lower().strip()

        for opt in options:
            key = str(opt.get("key", "")).strip()
            value = str(opt.get("value", "")).strip()

            # Exact match on key
            if key.lower() == user_lower:
                return key

            # Exact match on value
            if value.lower() == user_lower:
                return key

            # Match on just the key number (e.g., "1" matches "1. Option A")
            if key.split('.')[0].strip() == user_lower:
                return key

        return None

    def _fuzzy_match_options(
        self,
        user_input: str,
        options: List[Dict],
        threshold: float = 0.7
    ) -> Optional[Tuple[str, float]]:
        """
        Medium path: fuzzy string matching using sequence similarity.

        Returns: (matched_key, confidence) or None
        """
        user_lower = user_input.lower().strip()
        best_match = None
        best_score = 0.0

        for opt in options:
            key = str(opt.get("key", "")).strip()
            value = str(opt.get("value", "")).strip()

            # Check similarity with key
            key_score = SequenceMatcher(None, user_lower, key.lower()).ratio()

            # Check similarity with value
            value_score = SequenceMatcher(None, user_lower, value.lower()).ratio()

            # Check if user input contains key words
            key_words = set(key.lower().split())
            user_words = set(user_lower.split())
            word_overlap = len(key_words & user_words) / max(len(key_words), 1)

            # Take the best score
            score = max(key_score, value_score, word_overlap)

            if score > best_score:
                best_score = score
                best_match = key

        if best_match and best_score >= threshold:
            return (best_match, best_score)

        return None

    async def _llm_match_options(
        self,
        db: Session,
        company_id: int,
        user_input: str,
        options: List[Dict],
        prompt_context: str,
        llm_provider: str = "groq",
        llm_model: str = None
    ) -> Optional[Tuple[str, float, str]]:
        """
        Slow path: LLM semantic matching.

        Returns: (matched_key, confidence, reasoning) or None
        """
        # Sanitize user input to prevent prompt injection
        safe_user_input = self._sanitize_user_input(user_input)
        safe_prompt_context = self._sanitize_user_input(prompt_context)

        options_formatted = "\n".join([
            f"- Key: \"{opt.get('key', '')}\" | Label: \"{opt.get('value', '')}\""
            for opt in options
        ])

        prompt = f"""You are validating a user's response to a question with multiple choice options.

Question asked: "{safe_prompt_context}"

Available options:
{options_formatted}

User's response: "{safe_user_input}"

IMPORTANT: Only match if the user's response is CLEARLY related to one of the available options.

Match when:
- User types the exact option text or key (e.g., "street light" matches "street light")
- User types a number/index (e.g., "1" or "2" for first/second option)
- User types a close abbreviation or typo (e.g., "stret lite" matches "street light")
- User types a synonym that CLEARLY means the same thing

DO NOT match when:
- User's response is about a completely different topic (e.g., "housing" when options are about street lights)
- User's response is unrelated to any option
- User asks a question instead of selecting an option
- You're not confident the user meant one of the available options

If the response doesn't clearly match any option, return null with low confidence.

Respond with JSON only (no markdown):
{{
    "matched_option_key": "the exact key of the matched option, or null if no clear match",
    "confidence": 0.0-1.0,
    "reasoning": "brief explanation"
}}"""

        try:
            response = await self._generate_llm_response(db, company_id, prompt, temperature=0.1, max_tokens=200, provider=llm_provider, model=llm_model)
            if not response:
                return None

            # Parse JSON response
            result = self._parse_json_response(response)
            if not result:
                return None

            matched_key = result.get("matched_option_key")
            confidence = float(result.get("confidence", 0.0))
            reasoning = result.get("reasoning", "")

            if matched_key and matched_key != "null" and confidence >= 0.6:
                # Verify the key exists in options
                valid_keys = [str(opt.get("key", "")) for opt in options]
                if matched_key in valid_keys:
                    return (matched_key, confidence, reasoning)

        except Exception as e:
            print(f"Error in LLM option matching: {e}")

        return None

    async def _llm_check_relevance(
        self,
        db: Session,
        company_id: int,
        user_input: str,
        prompt_context: str,
        options: List[Dict] = None,
        llm_provider: str = "groq",
        llm_model: str = None
    ) -> Tuple[bool, str, str]:
        """
        Check if user response is relevant to the question (not off-topic).

        Returns: (is_relevant, reason, hint_if_not_relevant)
        """
        # Sanitize user input to prevent prompt injection
        safe_user_input = self._sanitize_user_input(user_input)
        safe_prompt_context = self._sanitize_user_input(prompt_context)

        # Build options context if available
        options_context = ""
        if options:
            options_list = [opt.get('value', opt.get('key', '')) for opt in options]
            options_context = f"\nAvailable options: {', '.join(options_list)}"

        prompt = f"""Determine if the user's response is relevant to the question and available options.

Question: "{safe_prompt_context}"{options_context}
User's response: "{safe_user_input}"

A response is IRRELEVANT if the user:
- Talks about a completely different topic unrelated to the available options
- Provides input that has nothing to do with any of the options
- Asks an unrelated question

A response is RELEVANT if the user:
- Attempts to select or reference one of the options (even if misspelled)
- Asks for clarification about the options
- Their response is clearly about the same topic as the options

Example: If options are about "street lights", a response about "housing" is IRRELEVANT.

Respond with JSON only (no markdown):
{{
    "is_relevant": true or false,
    "reason": "brief explanation"
}}"""

        try:
            response = await self._generate_llm_response(db, company_id, prompt, temperature=0.1, max_tokens=150, provider=llm_provider, model=llm_model)
            if not response:
                return (True, "", "")  # Default to accepting on LLM failure

            result = self._parse_json_response(response)
            if not result:
                return (True, "", "")

            is_relevant = result.get("is_relevant", True)
            reason = result.get("reason", "")

            hint = ""
            if not is_relevant:
                hint = f"I noticed you might have asked something else. Let me help you with the original question: {prompt_context}"

            return (is_relevant, reason, hint)

        except Exception as e:
            print(f"Error in LLM relevance check: {e}")
            return (True, "", "")  # Default to accepting on error

    async def _llm_validate_relevance(
        self,
        db: Session,
        company_id: int,
        user_input: str,
        question_text: str,
        expected_type: str,
        llm_provider: str = "groq",
        llm_model: str = None
    ) -> Tuple[bool, str, str, Optional[str]]:
        """
        Validate if response is relevant and appropriate for listen node.
        Also extracts the actual entity/answer from the response.

        Returns: (is_valid, reason, hint, extracted_value)
        """
        # Sanitize user input to prevent prompt injection
        safe_user_input = self._sanitize_user_input(user_input)
        safe_question_text = self._sanitize_user_input(question_text)

        type_context = ""
        if expected_type == "text":
            type_context = "Expected: text response"
        elif expected_type == "attachment":
            type_context = "Expected: image or file attachment"
        elif expected_type == "location":
            type_context = "Expected: location or address"

        prompt = f"""Analyze the user's response to the question.

Question/Context: "{safe_question_text}"
{type_context}
User's response: "{safe_user_input}"

Tasks:
1. Is the response relevant to the question?
2. Does it provide meaningful information?
3. Is it a genuine attempt to answer (not off-topic)?
4. If valid, extract the actual answer/entity from the response.

Extraction examples:
- Question: "What is your name?" Response: "my name is Yash" → Extract: "Yash"
- Question: "What is your email?" Response: "you can reach me at test@example.com" → Extract: "test@example.com"
- Question: "Where do you live?" Response: "I live in New York City" → Extract: "New York City"
- Question: "How old are you?" Response: "I am 25 years old" → Extract: "25"
- Question: "What is your phone number?" Response: "my number is 555-1234" → Extract: "555-1234"

Respond with JSON only (no markdown):
{{
    "is_valid": true or false,
    "reason": "brief explanation",
    "hint": "if invalid, a helpful message to guide the user",
    "extracted_value": "the extracted answer/entity, or null if cannot extract or invalid"
}}"""

        try:
            response = await self._generate_llm_response(db, company_id, prompt, temperature=0.1, max_tokens=250, provider=llm_provider, model=llm_model)
            if not response:
                return (True, "", "", None)

            result = self._parse_json_response(response)
            if not result:
                return (True, "", "", None)

            is_valid = result.get("is_valid", True)
            reason = result.get("reason", "")
            hint = result.get("hint", "")
            extracted_value = result.get("extracted_value")

            # Clean up extracted value
            if extracted_value and extracted_value.lower() in ["null", "none", ""]:
                extracted_value = None

            if not hint and not is_valid:
                hint = f"Please provide an answer to: {question_text}"

            return (is_valid, reason, hint, extracted_value)

        except Exception as e:
            print(f"Error in LLM validation: {e}")
            return (True, "", "", None)

    def _generate_options_hint(self, options: List[Dict]) -> str:
        """Generate a hint message listing available options."""
        if not options:
            return "Please provide a valid response."

        option_texts = []
        for opt in options[:5]:  # Limit to first 5 options
            value = opt.get("value", opt.get("key", ""))
            option_texts.append(f"- {value}")

        hint = "Please select one of the following options:\n" + "\n".join(option_texts)
        if len(options) > 5:
            hint += f"\n... and {len(options) - 5} more options"

        return hint

    async def _generate_llm_response(
        self,
        db: Session,
        company_id: int,
        prompt: str,
        temperature: float = 0.1,
        max_tokens: int = 200,
        provider: str = "groq",
        model: str = None
    ) -> str:
        """
        Generate LLM response for validation using configured provider.

        Args:
            db: Database session for credential lookup
            company_id: Company ID for credential lookup
            prompt: The prompt to send to the LLM
            temperature: Sampling temperature (default 0.1 for consistent results)
            max_tokens: Maximum tokens in response
            provider: LLM provider - "groq", "openai", or "google" (default: groq)
            model: Model name. If not specified, uses provider default:
                   - groq: llama-3.1-8b-instant
                   - openai: gpt-4o-mini
                   - google: gemini-1.5-flash
        """
        # Set default models per provider
        default_models = {
            "groq": "llama-3.1-8b-instant",
            "openai": "gpt-4o-mini",
            "google": "gemini-1.5-flash"
        }

        if not model:
            model = default_models.get(provider, "llama-3.1-8b-instant")

        try:
            if provider == "groq":
                return await self._call_groq(db, company_id, prompt, model, temperature, max_tokens)
            elif provider == "openai":
                return await self._call_openai(db, company_id, prompt, model, temperature, max_tokens)
            elif provider == "google":
                return await self._call_google(db, company_id, prompt, model, temperature, max_tokens)
            else:
                print(f"Unknown provider '{provider}', falling back to Groq")
                return await self._call_groq(db, company_id, prompt, model, temperature, max_tokens)

        except Exception as e:
            print(f"Error generating LLM response for validation ({provider}): {e}")
            return ""

    async def _call_groq(self, db: Session, company_id: int, prompt: str, model: str, temperature: float, max_tokens: int) -> str:
        """Call Groq API for validation using vault-stored credentials."""
        from groq import AsyncGroq

        # Get API key from vault
        credential = credential_service.get_credential_by_service_name(db, service_name="groq", company_id=company_id)
        if not credential:
            print(f"Please configure Groq API key in vault for LLM validation (company_id: {company_id})")
            return ""

        api_key = vault_service.decrypt(credential.encrypted_credentials)
        if not api_key:
            print(f"Failed to decrypt Groq API key from vault (company_id: {company_id})")
            return ""

        client = AsyncGroq(api_key=api_key, timeout=10.0)
        chat_completion = await client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return chat_completion.choices[0].message.content or ""

    async def _call_openai(self, db: Session, company_id: int, prompt: str, model: str, temperature: float, max_tokens: int) -> str:
        """Call OpenAI API for validation using vault-stored credentials."""
        from openai import AsyncOpenAI

        # Get API key from vault
        credential = credential_service.get_credential_by_service_name(db, service_name="openai", company_id=company_id)
        if not credential:
            print(f"Please configure OpenAI API key in vault for LLM validation (company_id: {company_id})")
            return ""

        api_key = vault_service.decrypt(credential.encrypted_credentials)
        if not api_key:
            print(f"Failed to decrypt OpenAI API key from vault (company_id: {company_id})")
            return ""

        client = AsyncOpenAI(api_key=api_key, timeout=10.0)
        chat_completion = await client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return chat_completion.choices[0].message.content or ""

    async def _call_google(self, db: Session, company_id: int, prompt: str, model: str, temperature: float, max_tokens: int) -> str:
        """Call Google Gemini API for validation using vault-stored credentials."""
        import google.generativeai as genai

        # Get API key from vault
        credential = credential_service.get_credential_by_service_name(db, service_name="gemini", company_id=company_id)
        if not credential:
            print(f"Please configure Gemini API key in vault for LLM validation (company_id: {company_id})")
            return ""

        api_key = vault_service.decrypt(credential.encrypted_credentials)
        if not api_key:
            print(f"Failed to decrypt Gemini API key from vault (company_id: {company_id})")
            return ""

        genai.configure(api_key=api_key)
        gen_model = genai.GenerativeModel(model)

        generation_config = genai.GenerationConfig(
            temperature=temperature,
            max_output_tokens=max_tokens
        )

        response = await gen_model.generate_content_async(
            prompt,
            generation_config=generation_config
        )
        return response.text or ""

    def _parse_json_response(self, response: str) -> Optional[Dict]:
        """Parse JSON from LLM response, handling markdown code blocks."""
        try:
            cleaned = response.strip()

            # Remove markdown code blocks if present
            if cleaned.startswith('```'):
                parts = cleaned.split('```')
                if len(parts) >= 2:
                    cleaned = parts[1]
                    if cleaned.startswith('json'):
                        cleaned = cleaned[4:]

            return json.loads(cleaned.strip())
        except json.JSONDecodeError as e:
            print(f"JSON parse error: {e}, response: {response[:100]}")
            return None
