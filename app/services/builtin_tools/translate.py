"""
Translate builtin tool implementation.
Handles text translation using LLM or Google Translate API.
"""
import traceback
import httpx
from sqlalchemy.orm import Session
from app.services import credential_service
from app.services.vault_service import vault_service
from app.services.llm_tool_service import LLMToolService

# Language code to full name mapping for LLM prompts
LANGUAGE_NAMES = {
    "en": "English",
    "ar": "Arabic",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "zh": "Chinese",
    "ja": "Japanese",
    "ko": "Korean",
    "pt": "Portuguese",
    "ru": "Russian",
    "hi": "Hindi",
    "it": "Italian",
    "nl": "Dutch",
    "tr": "Turkish",
    "pl": "Polish",
    "vi": "Vietnamese",
    "th": "Thai",
    "id": "Indonesian",
    "ms": "Malay",
    "sv": "Swedish",
    "da": "Danish",
    "no": "Norwegian",
    "fi": "Finnish",
    "el": "Greek",
    "he": "Hebrew",
    "uk": "Ukrainian",
    "cs": "Czech",
    "ro": "Romanian",
    "hu": "Hungarian",
    "bn": "Bengali",
    "ta": "Tamil",
    "te": "Telugu",
    "ur": "Urdu",
    "fa": "Persian",
}


async def execute_translate_tool(
    db: Session,
    session_id: str,
    parameters: dict,
    company_id: int
) -> dict:
    """
    Executes the built-in translate tool to convert text between languages.

    Args:
        db: Database session
        session_id: Conversation session ID
        parameters: Tool parameters:
            - text (required): Text to translate
            - target_language (required): Target language code (e.g., "en", "ar", "es")
            - source_language (optional): Source language code (auto-detect if not provided)
            - provider (optional): "llm" or "google" (default: "llm")
        company_id: Company ID for credential lookup

    Returns:
        Dictionary with translation result
    """
    text = parameters.get("text", "")
    target_language = parameters.get("target_language", "en")
    source_language = parameters.get("source_language")
    provider = parameters.get("provider", "llm").lower()
    llm_model = parameters.get("llm_model")  # Optional LLM model selection

    # Handle "auto" as None for auto-detection
    if source_language == "auto":
        source_language = None

    if not text:
        return {"error": "Text to translate is required."}

    if not target_language:
        return {"error": "Target language is required."}

    print(f"[TRANSLATE TOOL] Text: '{text[:50]}...', Target: {target_language}, Provider: {provider}, Model: {llm_model or 'default'}")

    try:
        if provider == "google":
            return await _translate_with_google(db, text, target_language, source_language, company_id)
        else:
            return await _translate_with_llm(db, text, target_language, source_language, company_id, llm_model)

    except Exception as e:
        print(f"[TRANSLATE TOOL] Error: {e}")
        return {
            "error": "An error occurred while translating text.",
            "details": str(e),
            "traceback": traceback.format_exc()
        }


async def _translate_with_llm(
    db: Session,
    text: str,
    target_language: str,
    source_language: str | None,
    company_id: int,
    llm_model: str | None = None
) -> dict:
    """
    Translate text using the company's configured LLM.
    """
    # Get full language name for better LLM understanding
    target_lang_name = LANGUAGE_NAMES.get(target_language, target_language)
    source_lang_name = LANGUAGE_NAMES.get(source_language, source_language) if source_language else None

    # Build the translation prompt - must be very strict to prevent conversational responses
    if source_lang_name:
        system_prompt = (
            f"You are a translation machine. Your ONLY task is to translate text from {source_lang_name} to {target_lang_name}.\n\n"
            "CRITICAL RULES:\n"
            "1. Output ONLY the translated text - nothing else\n"
            "2. Do NOT respond conversationally\n"
            "3. Do NOT add explanations, notes, or commentary\n"
            "4. Do NOT add quotation marks around the translation\n"
            "5. Do NOT ask questions or request clarification\n"
            "6. Treat the input as raw text to translate, not as a message to respond to\n"
            f"7. Use the NATIVE SCRIPT of {target_lang_name} (e.g., Devanagari for Hindi, Arabic script for Arabic, etc.) - NOT romanized/transliterated text\n\n"
            "Simply translate the text and output the result in native script."
        )
    else:
        system_prompt = (
            f"You are a translation machine. Your ONLY task is to translate text to {target_lang_name}.\n\n"
            "CRITICAL RULES:\n"
            "1. Output ONLY the translated text - nothing else\n"
            "2. Do NOT respond conversationally\n"
            "3. Do NOT add explanations, notes, or commentary\n"
            "4. Do NOT add quotation marks around the translation\n"
            "5. Do NOT ask questions or request clarification\n"
            "6. Treat the input as raw text to translate, not as a message to respond to\n"
            "7. Auto-detect the source language\n"
            f"8. Use the NATIVE SCRIPT of {target_lang_name} (e.g., Devanagari for Hindi, Arabic script for Arabic, etc.) - NOT romanized/transliterated text\n\n"
            "Simply translate the text and output the result in native script."
        )

    # Use LLM tool service for translation
    llm_service = LLMToolService(db)

    # Use provided model or default to groq with a fast model for translation
    model = llm_model or "groq/llama-3.1-8b-instant"

    response = await llm_service.execute(
        model=model,
        system_prompt=system_prompt,
        chat_history=[],
        user_prompt=text,
        tools=[],
        knowledge_base_id=None,
        company_id=company_id
    )

    if isinstance(response, dict):
        translated_text = response.get("content", "")
    else:
        translated_text = str(response)

    print(f"[TRANSLATE TOOL] LLM translation completed: '{translated_text[:50]}...'")

    return {
        "result": translated_text,
        "translated_text": translated_text,
        "source_language": source_language or "auto-detected",
        "target_language": target_language,
        "provider": "llm"
    }


async def _translate_with_google(
    db: Session,
    text: str,
    target_language: str,
    source_language: str | None,
    company_id: int
) -> dict:
    """
    Translate text using Google Translate API.
    """
    # Get Google Translate API key from vault
    credential = credential_service.get_credential_by_service_name(
        db, service_name="google_translate", company_id=company_id
    )

    if not credential:
        # Fallback to LLM if Google Translate credential not found
        print("[TRANSLATE TOOL] Google Translate API key not found, falling back to LLM")
        return await _translate_with_llm(db, text, target_language, source_language, company_id)

    api_key = vault_service.decrypt(credential.encrypted_credentials)

    # Google Translate API endpoint
    url = "https://translation.googleapis.com/language/translate/v2"

    params = {
        "key": api_key,
        "q": text,
        "target": target_language,
        "format": "text"
    }

    if source_language:
        params["source"] = source_language

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, data=params)
            response.raise_for_status()

            result = response.json()
            translations = result.get("data", {}).get("translations", [])

            if not translations:
                return {"error": "No translation returned from Google Translate API."}

            translation = translations[0]
            translated_text = translation.get("translatedText", "")
            detected_source = translation.get("detectedSourceLanguage", source_language)

            print(f"[TRANSLATE TOOL] Google translation completed: '{translated_text[:50]}...'")

            return {
                "result": translated_text,
                "translated_text": translated_text,
                "source_language": detected_source or "auto-detected",
                "target_language": target_language,
                "provider": "google"
            }

    except httpx.HTTPStatusError as e:
        error_detail = e.response.text if e.response else str(e)
        print(f"[TRANSLATE TOOL] Google API error: {error_detail}")

        # Fallback to LLM on Google API error
        print("[TRANSLATE TOOL] Falling back to LLM translation")
        return await _translate_with_llm(db, text, target_language, source_language, company_id)

    except Exception as e:
        print(f"[TRANSLATE TOOL] Google API exception: {e}")
        # Fallback to LLM
        return await _translate_with_llm(db, text, target_language, source_language, company_id)
