"""
Voice Option Extraction Service

Uses OpenAI's structured JSON output to extract the chosen option
from voice transcription when a workflow prompt is paused for input.
"""

import json
from typing import List, Dict, Optional
from sqlalchemy.orm import Session
from openai import AsyncOpenAI

from app.services import credential_service
from app.services.vault_service import vault_service

import logging

logger = logging.getLogger(__name__)


async def extract_chosen_option(
    db: Session,
    company_id: int,
    user_input: str,
    prompt_text: str,
    options: List[Dict]
) -> Optional[Dict]:
    """
    Extract the chosen option from voice input using OpenAI structured output.
    
    Args:
        db: Database session
        company_id: Company ID for credential lookup
        user_input: The transcribed voice input from user
        prompt_text: The original prompt/question shown to user
        options: List of {key, value} option dicts
        
    Returns:
        {"chosen_option": "option_key", "chosen_value": "Option Label", "confidence": 0.9} or None
    """
    if not user_input or not options:
        return None
    
    # Get OpenAI API key from vault
    credential = credential_service.get_credential_by_service_name(
        db, service_name="openai", company_id=company_id
    )
    if not credential:
        logger.warning(f"[Voice Extraction] OpenAI credential not found for company {company_id}")
        return None
    
    api_key = vault_service.decrypt(credential.encrypted_credentials)
    if not api_key:
        logger.warning(f"[Voice Extraction] Failed to decrypt OpenAI credential for company {company_id}")
        return None
    
    # Build options list for prompt
    options_text = "\n".join([
        f"- Key: \"{opt.get('key', '')}\", Label: \"{opt.get('value', '')}\""
        for opt in options
    ])
    
    # Also build a numbered list for "first", "second" etc. matching
    numbered_options = "\n".join([
        f"{i+1}. Key: \"{opt.get('key', '')}\", Label: \"{opt.get('value', '')}\""
        for i, opt in enumerate(options)
    ])
    
    prompt = f"""You are analyzing a user's voice response to select from given options.

Question asked to user: "{prompt_text}"

Available options (with keys and labels):
{options_text}

Numbered for reference:
{numbered_options}

User's voice response: "{user_input}"

Analyze the user's response and determine which option they chose.
If the user clearly selected one of the options (by saying the option label, number, key, or similar), return that option's KEY (not the label).

Consider:
- User might say "the first one", "option 1", "number 1" - return the KEY of the first option
- User might say "the second one", "option 2" - return the KEY of the second option  
- User might say the actual label text or abbreviate it
- User might have slight speech recognition errors or typos
- User might paraphrase the option

If you cannot determine which option they chose with reasonable confidence, return null for chosen_option."""

    # JSON schema for structured output
    json_schema = {
        "name": "chosen_option_response",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "chosen_option": {
                    "type": ["string", "null"],
                    "description": "The KEY of the option chosen by user, or null if unclear"
                },
                "confidence": {
                    "type": "number",
                    "description": "Confidence score from 0.0 to 1.0"
                },
                "reasoning": {
                    "type": "string",
                    "description": "Brief explanation of why this option was matched"
                }
            },
            "required": ["chosen_option", "confidence", "reasoning"]
        }
    }

    try:
        client = AsyncOpenAI(api_key=api_key, timeout=15.0)
        
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You extract the user's chosen option from their voice response. Always return valid JSON."},
                {"role": "user", "content": prompt}
            ],
            response_format={
                "type": "json_schema",
                "json_schema": json_schema
            },
            temperature=0.1,
            max_tokens=200
        )
        
        raw_text = response.choices[0].message.content
        result = json.loads(raw_text)
        
        chosen_key = result.get("chosen_option")
        confidence = result.get("confidence", 0.0)
        reasoning = result.get("reasoning", "")
        
        logger.info(f"[Voice Extraction] Result: key={chosen_key}, confidence={confidence}, reason={reasoning}")
        
        # Validate the key exists in options and confidence is sufficient
        if chosen_key and confidence >= 0.6:
            valid_keys = [str(opt.get("key", "")) for opt in options]
            if chosen_key in valid_keys:
                # Find the corresponding value (label)
                chosen_value = next(
                    (opt.get("value", "") for opt in options if opt.get("key") == chosen_key),
                    ""
                )
                return {
                    "chosen_option": chosen_key,
                    "chosen_value": chosen_value,
                    "confidence": confidence
                }
            else:
                logger.warning(f"[Voice Extraction] Extracted key '{chosen_key}' not in valid keys: {valid_keys}")
        
        return None
        
    except Exception as e:
        logger.error(f"[Voice Extraction] Error: {e}")
        import traceback
        traceback.print_exc()
        return None
