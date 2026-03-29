import json
import logging
import re
from typing import Dict, Any, List, Optional
from groq import AsyncGroq
from openai import AsyncOpenAI
from sqlalchemy.orm import Session

from app.services import credential_service
from app.services.vault_service import vault_service

logger = logging.getLogger(__name__)

LLM_PROVIDERS = {
    "groq": {"default_model": "llama-3.3-70b-versatile"},
    "openai": {"default_model": "gpt-4o-mini"},
}

PLATFORM_RULES = {
    "linkedin": (
        "LinkedIn post rules:\n"
        "- Max 3000 characters total\n"
        "- First 210 chars shown before 'see more' — make the hook irresistible\n"
        "- Professional yet personal tone\n"
        "- Use line breaks for readability\n"
        "- Include 3-5 relevant hashtags at the END of the post\n"
        "- No emojis required but 1-2 can work well"
    ),
    "instagram": (
        "Instagram caption rules:\n"
        "- Max 2200 characters; first 125 chars visible before 'more'\n"
        "- Visual-first, engaging, conversational tone\n"
        "- Line breaks and white space encouraged\n"
        "- Include 5-15 hashtags (can be at end or in first comment)\n"
        "- Emojis are encouraged to increase engagement"
    ),
    "facebook": (
        "Facebook post rules:\n"
        "- Aim for under 500 characters for best engagement (max 63206)\n"
        "- Conversational and friendly tone\n"
        "- 2-5 hashtags maximum\n"
        "- Ask a question or include a call-to-action to drive comments\n"
        "- Emojis optional but welcome"
    ),
}


class SocialContentAIService:
    """AI service for generating platform-optimized social media content."""

    def _get_client(self, provider: str, api_key: str):
        if provider == "groq":
            return AsyncGroq(api_key=api_key, timeout=60.0)
        elif provider == "openai":
            return AsyncOpenAI(api_key=api_key, timeout=60.0)
        raise ValueError(f"Unsupported provider: {provider}")

    def _get_api_key_from_credential(self, db: Session, credential_id: int, company_id: int):
        cred = credential_service.get_credential(db, credential_id, company_id)
        if not cred:
            raise ValueError("Credential not found")
        api_key = vault_service.decrypt(cred.encrypted_credentials)
        provider = cred.service.lower()
        if provider not in LLM_PROVIDERS:
            raise ValueError(f"Unsupported provider: {provider}")
        return api_key, provider

    def _get_fallback_client(self):
        """Use system-level Groq key as fallback when no credential_id provided."""
        from app.core.config import settings
        if settings.GROQ_API_KEY:
            return AsyncGroq(api_key=settings.GROQ_API_KEY, timeout=60.0), "groq"
        if settings.OPENAI_API_KEY:
            return AsyncOpenAI(api_key=settings.OPENAI_API_KEY, timeout=60.0), "openai"
        raise ValueError("No LLM credential configured. Please add a Groq or OpenAI credential.")

    def _parse_json_response(self, text: str) -> dict:
        """Extract JSON from LLM response, stripping markdown code fences if present."""
        text = text.strip()
        # Strip markdown code fences
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        # strict=False allows literal control characters (e.g. \n, \t) inside JSON strings
        return json.loads(text, strict=False)

    def _build_platform_instructions(self, platforms: List[str]) -> str:
        return "\n\n".join(
            PLATFORM_RULES[p] for p in platforms if p in PLATFORM_RULES
        )

    async def generate_from_topic(
        self,
        db: Session,
        company_id: int,
        credential_id: Optional[int],
        topic: str,
        tone: str = "professional",
        target_platforms: List[str] = None,
        include_hashtags: bool = True,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generate platform-optimized posts for a given topic."""
        if target_platforms is None:
            target_platforms = ["linkedin", "instagram", "facebook"]

        if credential_id:
            api_key, provider = self._get_api_key_from_credential(db, credential_id, company_id)
            client = self._get_client(provider, api_key)
        else:
            client, provider = self._get_fallback_client()

        model_id = model or LLM_PROVIDERS[provider]["default_model"]
        platform_rules = self._build_platform_instructions(target_platforms)
        platforms_str = ", ".join(target_platforms)

        system_prompt = f"""You are an expert social media content creator.
Generate engaging, platform-optimized posts for: {platforms_str}.
Tone: {tone}
{'Include relevant hashtags in each post.' if include_hashtags else 'Do not include hashtags.'}

Platform-specific rules:
{platform_rules}

Respond ONLY with valid JSON in this exact structure:
{{
{chr(10).join(f'  "{p}": {{"content": "...", "hashtags": [...], "character_count": 0}},' for p in target_platforms)}
}}
Replace character_count with the actual character count of the content field."""

        user_message = f"Create posts about: {topic}"

        response = await client.chat.completions.create(
            model=model_id,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=0.7,
        )

        raw = response.choices[0].message.content
        result = self._parse_json_response(raw)

        # Ensure character_count is accurate
        for platform in target_platforms:
            if platform in result:
                result[platform]["character_count"] = len(result[platform].get("content", ""))

        return {"platforms": result, "topic": topic, "tone": tone}

    async def generate_from_url(
        self,
        db: Session,
        company_id: int,
        credential_id: Optional[int],
        source_url: str,
        target_platforms: List[str] = None,
        adaptation_style: str = "inspired_by",
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Extract metadata from a URL then generate adapted posts."""
        from app.services.trending_content_service import TrendingContentService
        if target_platforms is None:
            target_platforms = ["linkedin", "instagram", "facebook"]

        # Fetch URL metadata
        trend_svc = TrendingContentService()
        metadata = await trend_svc.extract_post_metadata(source_url)

        style_instructions = {
            "inspired_by": "Create original posts inspired by the theme and topic of the source content.",
            "repurpose": "Repurpose the key insights from the source for each platform.",
            "commentary": "Write posts that add your own commentary and opinion on the source topic.",
        }.get(adaptation_style, "Create original posts inspired by the source content.")

        if credential_id:
            api_key, provider = self._get_api_key_from_credential(db, credential_id, company_id)
            client = self._get_client(provider, api_key)
        else:
            client, provider = self._get_fallback_client()

        model_id = model or LLM_PROVIDERS[provider]["default_model"]
        platform_rules = self._build_platform_instructions(target_platforms)
        platforms_str = ", ".join(target_platforms)

        context = f"""Source URL: {source_url}
Title: {metadata.get('title', 'N/A')}
Description: {metadata.get('description', 'N/A')}"""

        system_prompt = f"""You are an expert social media content creator.
{style_instructions}
Generate posts for: {platforms_str}

{platform_rules}

Respond ONLY with valid JSON:
{{
{chr(10).join(f'  "{p}": {{"content": "...", "hashtags": [...], "character_count": 0}},' for p in target_platforms)}
}}"""

        response = await client.chat.completions.create(
            model=model_id,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": context},
            ],
            temperature=0.7,
        )

        raw = response.choices[0].message.content
        result = self._parse_json_response(raw)
        for platform in target_platforms:
            if platform in result:
                result[platform]["character_count"] = len(result[platform].get("content", ""))

        return {
            "platforms": result,
            "source_url": source_url,
            "source_metadata": metadata,
            "adaptation_style": adaptation_style,
        }

    async def improve_post(
        self,
        db: Session,
        company_id: int,
        credential_id: Optional[int],
        content: str,
        platform: str,
        improvements: List[str],
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Improve an existing post based on requested improvements."""
        if credential_id:
            api_key, provider = self._get_api_key_from_credential(db, credential_id, company_id)
            client = self._get_client(provider, api_key)
        else:
            client, provider = self._get_fallback_client()

        model_id = model or LLM_PROVIDERS[provider]["default_model"]
        rules = PLATFORM_RULES.get(platform, "")
        improvements_str = ", ".join(improvements)

        system_prompt = f"""You are an expert social media content editor.
Improve the provided {platform} post with focus on: {improvements_str}

{rules}

Respond ONLY with valid JSON:
{{"improved_content": "...", "hashtags": [...], "changes_made": ["list of changes"], "character_count": 0}}"""

        response = await client.chat.completions.create(
            model=model_id,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Improve this post:\n\n{content}"},
            ],
            temperature=0.6,
        )

        raw = response.choices[0].message.content
        result = self._parse_json_response(raw)
        result["character_count"] = len(result.get("improved_content", ""))
        return result

    async def chat_about_post(
        self,
        db: Session,
        company_id: int,
        credential_id: Optional[int],
        message: str,
        history: List[dict],
        current_content: str,
        platform: str,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Chat to iteratively refine a social media post."""
        if credential_id:
            api_key, provider = self._get_api_key_from_credential(db, credential_id, company_id)
            client = self._get_client(provider, api_key)
        else:
            client, provider = self._get_fallback_client()

        model_id = model or LLM_PROVIDERS[provider]["default_model"]
        rules = PLATFORM_RULES.get(platform, "")

        system_prompt = f"""You are an expert social media content editor helping to refine a {platform} post.

{rules}

The user will give you instructions to edit, rewrite, shorten, expand, change tone, or improve the post.

Current post content:
\"\"\"
{current_content or "(empty — user hasn't written anything yet)"}
\"\"\"

Respond with valid JSON only:
{{"reply": "Your conversational response explaining what you changed.", "updated_content": "The full updated post text, or null if no change needed.", "updated_hashtags": ["tag1", "tag2"] or null}}

- Always include the complete updated post in `updated_content`, not just the changed part.
- Set `updated_content` to null only if the user is asking a question and no edit is needed.
- Do NOT include hashtags inside `updated_content` — put them in `updated_hashtags` only."""

        messages = [{"role": "system", "content": system_prompt}]
        for h in history:
            messages.append({"role": h["role"], "content": h["content"]})
        messages.append({"role": "user", "content": message})

        response = await client.chat.completions.create(
            model=model_id,
            messages=messages,
            temperature=0.7,
        )

        raw = response.choices[0].message.content
        result = self._parse_json_response(raw)
        return {
            "reply": result.get("reply", "Done!"),
            "updated_content": result.get("updated_content"),
            "updated_hashtags": result.get("updated_hashtags"),
        }
