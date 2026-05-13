import google.generativeai as genai
from sqlalchemy.orm import Session
from app.services import credential_service
from app.services.vault_service import vault_service
from app.core.config import settings
from PIL import Image
import io
import os
import uuid
import json
from typing import AsyncGenerator, Union, Dict, List
import logging
logger = logging.getLogger(__name__)

genai.configure(api_key=settings.GOOGLE_API_KEY)

async def generate_response(
    db: Session,
    company_id: int,
    model_name: str,
    system_prompt: str,
    chat_history: list,
    tools: list = None,
    api_key: str = None,
    tool_choice: str = "auto",
    stream: bool = None
) -> Union[Dict, AsyncGenerator[str, None]]:
    # Use settings default if stream parameter is not explicitly set
    if stream is None:
        stream = settings.LLM_STREAMING_ENABLED

    if api_key is None:
        credential = credential_service.get_credential_by_service_name(db, service_name="gemini", company_id=company_id)
        if not credential:
            raise ValueError("Gemini API key not found for this company.")
        api_key = vault_service.decrypt(credential.encrypted_credentials)

    if not api_key:
        raise ValueError("GOOGLE_API_KEY is not configured for this agent.")

    genai.configure(api_key=api_key)

    model = genai.GenerativeModel(
        model_name=model_name,
        system_instruction=system_prompt,
        tools=tools if tools else None
    )

    gemini_history = []
    for msg in chat_history:
        role = 'user' if msg.sender == 'user' else 'model'
        gemini_history.append({"role": role, "parts": [{"text": msg.message}]})

    user_prompt = gemini_history.pop(-1)['parts'][0]['text']

    model_chat_session = model.start_chat(history=gemini_history)

    # STREAMING MODE: Cannot use tools with streaming currently
    if stream and not tools:
        async def stream_response():
            full_content = ""
            try:
                response = await model_chat_session.send_message_async(user_prompt, stream=True)

                async for chunk in response:
                    if chunk.text:
                        token = chunk.text
                        full_content += token
                        yield json.dumps({"type": "stream", "content": token})

                # Send final message indicating completion
                yield json.dumps({"type": "stream_end", "full_content": full_content})

            except Exception as e:
                yield json.dumps({"type": "error", "content": f"LLM provider error: {e}"})

        return stream_response()

    # NON-STREAMING MODE: Original logic with tool support
    response = await model_chat_session.send_message_async(user_prompt)

    # Extract usage data if available
    usage_data = None
    try:
        if hasattr(response, 'usage_metadata') and response.usage_metadata:
            usage_data = {
                "prompt_tokens": response.usage_metadata.prompt_token_count or 0,
                "completion_tokens": response.usage_metadata.candidates_token_count or 0,
                "total_tokens": response.usage_metadata.total_token_count or 0
            }
    except (AttributeError, TypeError):
        logger.exception("Unexpected error")

    try:
        function_call = response.candidates[0].content.parts[0].function_call
        if function_call:
            return {
                "type": "tool_call",
                "tool_name": function_call.name,
                "parameters": {key: value for key, value in function_call.args.items()},
                "usage": usage_data
            }
    except (ValueError, AttributeError, IndexError):
        logger.exception("Unexpected error")

    return {"type": "text", "content": response.text, "usage": usage_data}

def generate_image(db: Session, company_id: int, prompt: str, api_key: str = None):
    """
    Generate an image using Google's Imagen API via vault credentials.

    Args:
        db: Database session
        company_id: Company ID for vault lookup
        prompt: Image generation prompt
        api_key: Optional API key override

    Returns:
        PIL Image object
    """
    # Get API key from vault if not provided
    if api_key is None:
        credential = credential_service.get_credential_by_service_name(
            db, service_name="gemini", company_id=company_id
        )
        if credential:
            api_key = vault_service.decrypt(credential.encrypted_credentials)

    # Fallback to settings if no vault credential
    if not api_key:
        api_key = settings.GOOGLE_API_KEY

    if not api_key:
        raise ValueError("Google API key not found. Please add a 'gemini' credential in the vault.")

    # Configure with the API key
    genai.configure(api_key=api_key)

    # Use Imagen 3 for image generation
    from google import genai as google_genai
    from google.genai import types

    client = google_genai.Client(api_key=api_key)

    try:
        # Try Imagen 3 first (best quality)
        response = client.models.generate_images(
            model='imagen-3.0-generate-002',
            prompt=prompt,
            config=types.GenerateImagesConfig(
                number_of_images=1,
                aspect_ratio="1:1",
                safety_filter_level="BLOCK_MEDIUM_AND_ABOVE",
            )
        )

        if response.generated_images:
            image_data = response.generated_images[0].image.image_bytes
            image = Image.open(io.BytesIO(image_data))
            return image
        else:
            raise ValueError("No image generated")

    except Exception as e:

        # Fallback to Gemini 2.0 Flash experimental
        try:
            model = genai.GenerativeModel('gemini-2.0-flash-exp')
            response = model.generate_content(
                f"Generate an image of: {prompt}",
                generation_config=genai.types.GenerationConfig(
                    response_mime_type="image/png"
                )
            )

            for part in response.candidates[0].content.parts:
                if part.inline_data is not None:
                    image = Image.open(io.BytesIO(part.inline_data.data))
                    return image

            raise ValueError("No image generated from Gemini")

        except Exception as e2:
            raise ValueError(f"Image generation failed: {e2}")
