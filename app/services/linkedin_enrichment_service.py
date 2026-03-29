import json
import logging
import re
from datetime import datetime
from typing import List, Dict, Any, Optional
import httpx
from groq import AsyncGroq
from openai import AsyncOpenAI
from sqlalchemy.orm import Session

from app.models.contact import Contact
from app.models.lead import Lead
from app.models.social_account import SocialPlatform, SocialAccountStatus
from app.services.vault_service import vault_service
from app.core.config import settings

logger = logging.getLogger(__name__)


class LinkedInEnrichmentService:
    """
    Enriches contacts from LinkedIn profile URLs using two strategies:
      A) AI knowledge enrichment (no LinkedIn API required — works immediately)
      B) LinkedIn People API (requires connected SocialAccount with r_liteprofile scope)
    """

    def _parse_linkedin_url(self, url: str) -> Optional[str]:
        """Extract the /in/username slug from a LinkedIn URL."""
        url = url.strip().rstrip("/")
        m = re.search(r"linkedin\.com/in/([^/?#]+)", url, re.IGNORECASE)
        return m.group(1) if m else None

    def _get_llm_client(self):
        if settings.GROQ_API_KEY:
            return AsyncGroq(api_key=settings.GROQ_API_KEY, timeout=30.0), "groq"
        if settings.OPENAI_API_KEY:
            return AsyncOpenAI(api_key=settings.OPENAI_API_KEY, timeout=30.0), "openai"
        raise ValueError("No LLM API key configured for enrichment")

    async def enrich_from_url(
        self,
        db: Session,
        company_id: int,
        linkedin_url: str,
        social_account_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Strategy A: AI knowledge enrichment from LinkedIn profile slug.
        Returns enrichment dict. Does NOT save to DB — caller decides.
        """
        slug = self._parse_linkedin_url(linkedin_url)
        if not slug:
            raise ValueError(f"Could not parse LinkedIn URL: {linkedin_url}")

        client, provider = self._get_llm_client()
        model = "llama-3.3-70b-versatile" if provider == "groq" else "gpt-4o-mini"

        system_prompt = """You are a professional data enrichment assistant.
Given a LinkedIn profile username/slug, return what you know about this person from public information.
If you don't know something, return null for that field — never fabricate data.
Respond ONLY with valid JSON:
{
  "name": "...",
  "job_title": "...",
  "company_name": "...",
  "industry": "...",
  "location": "...",
  "headline": "...",
  "confidence": 0.0
}
confidence should be 0.0-1.0 reflecting how certain you are about this person."""

        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Enrich profile for LinkedIn slug: {slug}"},
            ],
            temperature=0.1,
        )

        raw = response.choices[0].message.content.strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = {}

        return {
            "linkedin_url": linkedin_url,
            "linkedin_slug": slug,
            "name": data.get("name"),
            "job_title": data.get("job_title"),
            "company_name": data.get("company_name"),
            "industry": data.get("industry"),
            "location": data.get("location"),
            "headline": data.get("headline"),
            "enrichment_source": "ai_knowledge",
            "confidence": data.get("confidence", 0.5),
        }

    async def enrich_via_api(
        self,
        db: Session,
        social_account_id: int,
        company_id: int,
        linkedin_urn: str,
    ) -> Dict[str, Any]:
        """
        Strategy B: LinkedIn People API enrichment.
        Requires a connected SocialAccount with r_liteprofile scope.
        """
        from app.models.social_account import SocialAccount
        account = db.query(SocialAccount).filter(
            SocialAccount.id == social_account_id,
            SocialAccount.company_id == company_id,
            SocialAccount.platform == SocialPlatform.LINKEDIN,
            SocialAccount.status == SocialAccountStatus.ACTIVE,
        ).first()
        if not account:
            raise ValueError("No active LinkedIn account found")

        creds = json.loads(vault_service.decrypt(account.credentials))
        access_token = creds.get("access_token")

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"https://api.linkedin.com/v2/people/(id:{linkedin_urn})",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "X-Restli-Protocol-Version": "2.0.0",
                },
                params={"projection": "(id,localizedFirstName,localizedLastName,headline,location)"},
            )
            if resp.status_code != 200:
                raise ValueError(f"LinkedIn API error: {resp.status_code}")
            data = resp.json()

        return {
            "linkedin_urn": linkedin_urn,
            "name": f"{data.get('localizedFirstName', '')} {data.get('localizedLastName', '')}".strip(),
            "headline": data.get("headline", {}).get("text") if isinstance(data.get("headline"), dict) else data.get("headline"),
            "location": data.get("location", {}).get("name") if isinstance(data.get("location"), dict) else None,
            "enrichment_source": "linkedin_api",
            "confidence": 1.0,
        }

    async def bulk_import_leads(
        self,
        db: Session,
        company_id: int,
        linkedin_urls: List[str],
    ) -> List[Dict[str, Any]]:
        """
        Import multiple LinkedIn profiles as leads.
        Returns list of results with status per URL.
        """
        results = []
        for url in linkedin_urls:
            url = url.strip()
            if not url:
                continue
            try:
                enrichment = await self.enrich_from_url(db, company_id, url)
                contact, lead = await self._create_contact_and_lead(db, company_id, enrichment)
                results.append({
                    "url": url,
                    "status": "success",
                    "contact_id": contact.id,
                    "lead_id": lead.id,
                    "name": enrichment.get("name"),
                    "job_title": enrichment.get("job_title"),
                    "company_name": enrichment.get("company_name"),
                })
            except Exception as e:
                logger.error(f"Failed to import {url}: {e}")
                results.append({"url": url, "status": "failed", "error": str(e)})
        return results

    async def _create_contact_and_lead(
        self,
        db: Session,
        company_id: int,
        enrichment: Dict[str, Any],
    ):
        """Create or update a Contact and create a Lead from enrichment data."""
        from app.models.lead import Lead, LeadStage, QualificationStatus

        linkedin_url = enrichment.get("linkedin_url", "")
        slug = enrichment.get("linkedin_slug", "")

        # Try to find existing contact by linkedin_url
        contact = db.query(Contact).filter(
            Contact.company_id == company_id,
            Contact.linkedin_url == linkedin_url,
        ).first()

        if not contact:
            # Generate a placeholder email from slug to satisfy unique constraint
            placeholder_email = f"linkedin_{slug}@placeholder.heygenally.com" if slug else None
            existing_by_email = db.query(Contact).filter(
                Contact.email == placeholder_email,
                Contact.company_id == company_id,
            ).first() if placeholder_email else None

            if existing_by_email:
                contact = existing_by_email
            else:
                contact = Contact(
                    company_id=company_id,
                    email=placeholder_email,
                    name=enrichment.get("name"),
                    linkedin_url=linkedin_url,
                    job_title=enrichment.get("job_title"),
                    company_name=enrichment.get("company_name"),
                    industry=enrichment.get("industry"),
                    location=enrichment.get("location"),
                    lead_source="linkedin_import",
                    enriched_at=datetime.utcnow(),
                    enrichment_source=enrichment.get("enrichment_source", "ai_knowledge"),
                )
                db.add(contact)
                db.flush()
        else:
            # Update enrichment fields
            if enrichment.get("job_title"):
                contact.job_title = enrichment["job_title"]
            if enrichment.get("company_name"):
                contact.company_name = enrichment["company_name"]
            if enrichment.get("industry"):
                contact.industry = enrichment["industry"]
            if enrichment.get("location"):
                contact.location = enrichment["location"]
            contact.enriched_at = datetime.utcnow()
            contact.enrichment_source = enrichment.get("enrichment_source", "ai_knowledge")
            db.flush()

        # Check if a lead already exists for this contact
        existing_lead = db.query(Lead).filter(
            Lead.contact_id == contact.id,
            Lead.company_id == company_id,
        ).first()

        if existing_lead:
            db.commit()
            return contact, existing_lead

        lead = Lead(
            contact_id=contact.id,
            company_id=company_id,
            source="linkedin_import",
            stage=LeadStage.LEAD,
            qualification_status=QualificationStatus.UNQUALIFIED,
        )
        db.add(lead)
        db.commit()
        return contact, lead
