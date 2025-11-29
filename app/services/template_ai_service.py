import re
import json
import logging
from typing import List, Dict, Any, Optional
from groq import AsyncGroq
from openai import AsyncOpenAI
from sqlalchemy.orm import Session

from app.services import credential_service
from app.services.vault_service import vault_service

logger = logging.getLogger(__name__)

# Supported LLM providers and their default models
LLM_PROVIDERS = {
    "groq": {
        "name": "Groq",
        "models": [
            {"id": "llama-3.3-70b-versatile", "name": "Llama 3.3 70B"},
            {"id": "llama-3.1-8b-instant", "name": "Llama 3.1 8B (Fast)"},
            {"id": "mixtral-8x7b-32768", "name": "Mixtral 8x7B"},
        ],
        "default_model": "llama-3.3-70b-versatile"
    },
    "openai": {
        "name": "OpenAI",
        "models": [
            {"id": "gpt-4o", "name": "GPT-4o"},
            {"id": "gpt-4o-mini", "name": "GPT-4o Mini"},
            {"id": "gpt-4-turbo", "name": "GPT-4 Turbo"},
        ],
        "default_model": "gpt-4o-mini"
    }
}


class TemplateAIService:
    """
    AI-powered service for generating and improving campaign templates.
    Uses vault credentials for LLM providers.
    """

    def __init__(self):
        pass

    def _get_client(self, provider: str, api_key: str):
        """Get the appropriate client for the provider."""
        if provider == "groq":
            return AsyncGroq(api_key=api_key, timeout=60.0)
        elif provider == "openai":
            return AsyncOpenAI(api_key=api_key, timeout=60.0)
        else:
            raise ValueError(f"Unsupported provider: {provider}")

    def _get_api_key_from_credential(self, db: Session, credential_id: int, company_id: int) -> tuple[str, str]:
        """
        Get API key and provider from credential.
        Returns (api_key, provider)
        """
        credential = credential_service.get_credential(db, credential_id, company_id)
        if not credential:
            raise ValueError("Credential not found")

        api_key = vault_service.decrypt(credential.encrypted_credentials)
        provider = credential.service.lower()

        if provider not in LLM_PROVIDERS:
            raise ValueError(f"Unsupported provider: {provider}. Supported: {list(LLM_PROVIDERS.keys())}")

        return api_key, provider

    def get_available_providers(self) -> List[Dict[str, Any]]:
        """Get list of supported LLM providers and their models."""
        return [
            {
                "service": key,
                "name": value["name"],
                "models": value["models"],
                "default_model": value["default_model"]
            }
            for key, value in LLM_PROVIDERS.items()
        ]

    async def generate_template(
        self,
        db: Session,
        company_id: int,
        credential_id: int,
        template_type: str,
        prompt: str,
        tone: str = "professional",
        target_audience: Optional[str] = None,
        campaign_goal: Optional[str] = None,
        include_cta: bool = True,
        language: str = "en",
        model: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Generate a complete template based on user prompt and parameters.
        Uses vault credential for LLM provider.
        """
        # Get API key and provider from credential
        api_key, provider = self._get_api_key_from_credential(db, credential_id, company_id)
        client = self._get_client(provider, api_key)

        # Use provided model or default for provider
        model_id = model or LLM_PROVIDERS[provider]["default_model"]

        type_instructions = self._get_type_instructions(template_type)

        system_prompt = f"""You are an expert marketing copywriter specializing in {template_type} campaigns.
Your task is to create compelling, high-converting content.

Content Guidelines:
- Tone: {tone}
- Language: {language}
{f'- Target Audience: {target_audience}' if target_audience else ''}
{f'- Campaign Goal: {campaign_goal}' if campaign_goal else ''}
{f'- Include a clear call-to-action' if include_cta else ''}

{type_instructions}

IMPORTANT: You can use these personalization tokens in your content:
- {{{{first_name}}}} - Recipient's first name
- {{{{last_name}}}} - Recipient's last name
- {{{{company}}}} - Recipient's company
- {{{{job_title}}}} - Recipient's job title

Respond in JSON format with the following structure:
{{
    "subject": "Email subject line (only for email type)",
    "body": "Plain text body content",
    "html_body": "HTML formatted body (only for email type)",
    "personalization_tokens": ["list", "of", "tokens", "used"],
    "suggestions": ["optional improvement suggestions"]
}}"""

        user_message = f"Create a {template_type} template for: {prompt}"

        try:
            response = await client.chat.completions.create(
                model=model_id,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message}
                ],
                temperature=0.7,
                max_tokens=2000
            )

            content = response.choices[0].message.content

            # Parse JSON response
            result = self._parse_json_response(content)

            # Clean up HTML body if present (remove excessive whitespace)
            if result.get("html_body"):
                result["html_body"] = self._clean_html(result["html_body"])

            # Extract tokens from content if not provided
            if not result.get("personalization_tokens"):
                result["personalization_tokens"] = self._extract_tokens(
                    result.get("body", "") + result.get("subject", "")
                )

            return result

        except Exception as e:
            logger.exception(f"Failed to generate template: {e}")
            raise Exception(f"Failed to generate template: {str(e)}")

    async def generate_subject_lines(
        self,
        db: Session,
        company_id: int,
        credential_id: int,
        body: str,
        count: int = 5,
        tone: str = "professional",
        model: Optional[str] = None
    ) -> List[str]:
        """
        Generate multiple subject line suggestions based on email body.
        """
        api_key, provider = self._get_api_key_from_credential(db, credential_id, company_id)
        client = self._get_client(provider, api_key)
        model_id = model or LLM_PROVIDERS[provider]["default_model"]

        system_prompt = f"""You are an email marketing expert. Generate {count} compelling subject lines for the email content provided.

Guidelines:
- Tone: {tone}
- Keep subject lines under 60 characters
- Make them attention-grabbing but not spammy
- Avoid ALL CAPS and excessive punctuation
- Use personalization tokens where appropriate ({{{{first_name}}}}, etc.)

Respond with a JSON array of subject lines:
["Subject 1", "Subject 2", ...]"""

        try:
            response = await client.chat.completions.create(
                model=model_id,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Generate subject lines for this email:\n\n{body[:1500]}"}
                ],
                temperature=0.8,
                max_tokens=500
            )

            content = response.choices[0].message.content
            subjects = self._parse_json_response(content)

            if isinstance(subjects, list):
                return subjects[:count]
            return []

        except Exception as e:
            raise Exception(f"Failed to generate subject lines: {str(e)}")

    async def improve_content(
        self,
        db: Session,
        company_id: int,
        credential_id: int,
        content: str,
        content_type: str,
        improvements: List[str],
        model: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Improve existing content based on specified criteria.
        """
        api_key, provider = self._get_api_key_from_credential(db, credential_id, company_id)
        client = self._get_client(provider, api_key)
        model_id = model or LLM_PROVIDERS[provider]["default_model"]

        improvement_list = ", ".join(improvements)

        type_context = {
            "subject": "email subject line",
            "body": "message body",
            "html_body": "HTML email body",
            "voice_script": "voice call script"
        }.get(content_type, "content")

        system_prompt = f"""You are an expert copywriter. Improve the provided {type_context} based on these criteria: {improvement_list}.

Maintain the core message and any personalization tokens (like {{{{first_name}}}}).
Preserve the overall structure and intent.

Respond in JSON format:
{{
    "improved_content": "The improved content here",
    "changes_made": ["List of specific changes made"]
}}"""

        try:
            response = await client.chat.completions.create(
                model=model_id,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Improve this {type_context}:\n\n{content}"}
                ],
                temperature=0.7,
                max_tokens=2000
            )

            result = self._parse_json_response(response.choices[0].message.content)
            return result

        except Exception as e:
            raise Exception(f"Failed to improve content: {str(e)}")

    async def generate_ab_variants(
        self,
        db: Session,
        company_id: int,
        credential_id: int,
        original_subject: Optional[str],
        original_body: str,
        variant_count: int = 2,
        variation_type: str = "subject",
        model: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Generate A/B test variants of the original template.
        """
        api_key, provider = self._get_api_key_from_credential(db, credential_id, company_id)
        client = self._get_client(provider, api_key)
        model_id = model or LLM_PROVIDERS[provider]["default_model"]

        system_prompt = f"""You are an A/B testing expert. Generate {variant_count} variations of the provided content for testing.

Variation type: {variation_type}

Guidelines:
- Each variant should be meaningfully different
- Maintain the same core message and intent
- Preserve personalization tokens
- For subject variations: test different hooks, lengths, or emotional appeals
- For body variations: test different structures, CTAs, or emphasis

Respond in JSON format:
{{
    "variants": [
        {{
            "subject": "Variant subject (if applicable)",
            "body": "Variant body",
            "variation_description": "What makes this variant different"
        }}
    ]
}}"""

        content_to_vary = f"Subject: {original_subject}\n\nBody:\n{original_body}" if original_subject else original_body

        try:
            response = await client.chat.completions.create(
                model=model_id,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Create {variant_count} A/B test variants:\n\n{content_to_vary}"}
                ],
                temperature=0.9,
                max_tokens=3000
            )

            result = self._parse_json_response(response.choices[0].message.content)
            return result.get("variants", [])

        except Exception as e:
            raise Exception(f"Failed to generate variants: {str(e)}")

    def _get_type_instructions(self, template_type: str) -> str:
        """Get specific instructions based on template type."""
        instructions = {
            "email": """Email Template Requirements:
- Create a compelling subject line (under 60 characters)
- Write a clear, scannable body with short paragraphs
- Include HTML formatting with proper structure
- Add a clear call-to-action button/link
- Keep the email concise but impactful""",

            "sms": """SMS Template Requirements:
- Keep message under 160 characters if possible (320 max)
- Be direct and action-oriented
- Include a clear CTA
- Avoid special characters that may not render
- No HTML formatting""",

            "whatsapp": """WhatsApp Template Requirements:
- Keep message conversational but professional
- Can include emoji sparingly
- Include a clear call-to-action
- Format for easy mobile reading
- Max 1024 characters""",

            "voice": """Voice Script Requirements:
- Write in a natural, conversational tone
- Keep sentences short and clear
- Include pauses (marked as [pause])
- Add pronunciation notes for complex words
- Include response handling for common scenarios
- Duration should be 30-60 seconds when spoken"""
        }
        return instructions.get(template_type, "")

    def _extract_tokens(self, content: str) -> List[str]:
        """Extract personalization tokens from content."""
        pattern = r'\{\{([^}]+)\}\}'
        matches = re.findall(pattern, content)
        return [f"{{{{{match}}}}}" for match in set(matches)]

    def _clean_html(self, html: str) -> str:
        """Clean up HTML content from AI-generated responses."""
        if not html:
            return html

        # Remove leading/trailing whitespace from each line but preserve structure
        lines = html.split('\n')
        cleaned_lines = [line.strip() for line in lines if line.strip()]
        html = ' '.join(cleaned_lines)

        # Remove excessive whitespace between tags
        html = re.sub(r'>\s+<', '><', html)

        # Remove extra spaces within tags
        html = re.sub(r'\s+', ' ', html)

        # Ensure proper HTML structure
        html = html.strip()

        return html

    def _parse_json_response(self, content: str) -> Any:
        """Parse JSON from LLM response, handling various formats."""
        # Try to extract JSON from markdown code blocks
        json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', content)
        if json_match:
            content = json_match.group(1)

        # Clean up the content
        content = content.strip()

        try:
            return json.loads(content)
        except json.JSONDecodeError:
            # Try to find JSON object or array in the content
            obj_match = re.search(r'(\{[\s\S]*\}|\[[\s\S]*\])', content)
            if obj_match:
                try:
                    return json.loads(obj_match.group(1))
                except json.JSONDecodeError:
                    pass

            # Return as plain text if JSON parsing fails
            return {"body": content, "personalization_tokens": []}


# Singleton instance
template_ai_service = TemplateAIService()
