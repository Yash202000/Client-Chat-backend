import uuid
import io
import httpx
from sqlalchemy.orm import Session
from botocore.client import Config
import boto3
from app.core.object_storage import s3_client, BUCKET_NAME, endpoint_url
from app.core.config import settings
from app.crud import crud_ai_image
from app.schemas import ai_image as schemas_ai_image
from app.services import credential_service
from app.services.vault_service import vault_service
from PIL import Image
import logging
logger = logging.getLogger(__name__)


def _generate_proxy_url(key: str) -> str:
    """
    Generate a backend proxy URL for serving images.
    Images are served through /api/v1/ai-images/file/{filename}
    """
    # Extract just the filename from the key
    filename = key.replace("ai-images/", "") if key.startswith("ai-images/") else key
    return f"/api/v1/ai-images/file/{filename}"


def _get_api_key(db: Session, company_id: int, service_name: str, fallback_key: str = None) -> str:
    """Get API key from vault or fallback to settings."""
    credential = credential_service.get_credential_by_service_name(
        db, service_name=service_name, company_id=company_id
    )
    if credential:
        return vault_service.decrypt(credential.encrypted_credentials)
    return fallback_key


def _generate_with_openai(api_key: str, prompt: str, size: str, quality: str, style: str) -> bytes:
    """Generate image using OpenAI DALL-E 3."""
    import openai

    client = openai.OpenAI(api_key=api_key)

    response = client.images.generate(
        model="dall-e-3",
        prompt=prompt,
        size=size,
        quality=quality,
        style=style,
        n=1,
        response_format="url"
    )

    # Download the image from URL
    image_url = response.data[0].url
    image_response = httpx.get(image_url)
    image_response.raise_for_status()

    return image_response.content


def _generate_with_gemini(api_key: str, prompt: str) -> bytes:
    """Generate image using Google Imagen 3."""
    try:
        from google import genai as google_genai
        from google.genai import types

        client = google_genai.Client(api_key=api_key)

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
            return response.generated_images[0].image.image_bytes

        raise ValueError("No image generated from Imagen")

    except Exception as e:

        # Fallback to Gemini 2.0 Flash experimental
        import google.generativeai as genai
        genai.configure(api_key=api_key)

        model = genai.GenerativeModel('gemini-2.0-flash-exp')
        response = model.generate_content(
            f"Generate an image of: {prompt}",
            generation_config=genai.types.GenerationConfig(
                response_mime_type="image/png"
            )
        )

        for part in response.candidates[0].content.parts:
            if part.inline_data is not None:
                return part.inline_data.data

        raise ValueError(f"Image generation failed: {e}")


def create_and_upload_ai_image(db: Session, image_data: schemas_ai_image.AIImageCreate, company_id: int):
    """
    Generate and upload an AI image using the selected provider.

    Providers:
    - openai: Uses DALL-E 3 (requires 'openai' credential in vault)
    - gemini: Uses Imagen 3 (requires 'gemini' credential in vault)
    """
    prompt = image_data.prompt
    provider = image_data.provider

    # Get API key based on provider
    if provider == "openai":
        api_key = _get_api_key(db, company_id, "openai", settings.OPENAI_API_KEY)
        if not api_key:
            raise ValueError("OpenAI API key not found. Add 'openai' credential in vault.")

        image_bytes = _generate_with_openai(
            api_key=api_key,
            prompt=prompt,
            size=image_data.size or "1024x1024",
            quality=image_data.quality or "standard",
            style=image_data.style or "vivid"
        )

    elif provider == "gemini":
        api_key = _get_api_key(db, company_id, "gemini", settings.GOOGLE_API_KEY)
        if not api_key:
            raise ValueError("Google API key not found. Add 'gemini' credential in vault.")

        image_bytes = _generate_with_gemini(api_key=api_key, prompt=prompt)

    else:
        raise ValueError(f"Unknown provider: {provider}")

    # Upload to MinIO
    filename = f"ai-images/{uuid.uuid4()}.png"
    s3_client.put_object(
        Bucket=BUCKET_NAME,
        Key=filename,
        Body=image_bytes,
        ContentType='image/png'
    )

    # Generate a pre-signed URL (valid for 7 days)
    image_url = _generate_proxy_url(filename)

    # Save to database with generation params
    generation_params = {
        "provider": provider,
        "size": image_data.size,
        "quality": image_data.quality,
        "style": image_data.style,
    }

    return crud_ai_image.create_ai_image(
        db=db,
        prompt=prompt,
        image_url=image_url,
        generation_params=generation_params
    )

def get_ai_images(db: Session, skip: int = 0, limit: int = 100):
    """Get all AI images with fresh pre-signed URLs."""
    images = crud_ai_image.get_ai_images(db, skip=skip, limit=limit)

    # Refresh URLs for each image
    for image in images:
        image.image_url = _refresh_image_url(image.image_url)

    return images


def get_ai_image(db: Session, image_id: int):
    """Get a single AI image with fresh pre-signed URL."""
    image = crud_ai_image.get_ai_image(db, image_id)
    if image:
        image.image_url = _refresh_image_url(image.image_url)
    return image


def _refresh_image_url(url: str) -> str:
    """Extract the key from a URL and generate a fresh pre-signed URL."""
    if not url:
        return url

    # Extract the key from the URL
    # URL format: http://host:port/bucket/key or presigned URL
    try:
        # Check if it's already a presigned URL or direct URL
        if 'ai-images/' in url:
            # Extract the key part (ai-images/uuid.png)
            key_start = url.find('ai-images/')
            if key_start != -1:
                # Find the end of the key (before query params if any)
                key_end = url.find('?', key_start)
                if key_end == -1:
                    key = url[key_start:]
                else:
                    key = url[key_start:key_end]

                return _generate_proxy_url(key)
    except Exception as e:
        logger.exception(e)

    return url


def delete_ai_image(db: Session, image_id: int):
    """Delete an AI image from database and MinIO."""
    image = crud_ai_image.get_ai_image(db, image_id)
    if image:
        # Try to delete from MinIO
        try:
            if 'ai-images/' in image.image_url:
                key_start = image.image_url.find('ai-images/')
                if key_start != -1:
                    key_end = image.image_url.find('?', key_start)
                    if key_end == -1:
                        key = image.image_url[key_start:]
                    else:
                        key = image.image_url[key_start:key_end]
                    s3_client.delete_object(Bucket=BUCKET_NAME, Key=key)
        except Exception as e:
            logger.exception(e)

    return crud_ai_image.delete_ai_image(db=db, image_id=image_id)
