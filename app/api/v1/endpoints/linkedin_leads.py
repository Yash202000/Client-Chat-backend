import csv
import io
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.dependencies import get_db
from app.models.contact import Contact
from app.models.lead import Lead
from app.models.user import User
from app.services.linkedin_enrichment_service import LinkedInEnrichmentService

router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ImportURLRequest(BaseModel):
    linkedin_url: str
    social_account_id: Optional[int] = None


class BulkImportRequest(BaseModel):
    linkedin_urls: List[str]
    social_account_id: Optional[int] = None


class EnrichContactRequest(BaseModel):
    social_account_id: Optional[int] = None


class LinkedInOutreachRequest(BaseModel):
    name: str
    contact_ids: List[int]
    messages: List[dict]  # [{sequence_order, subject, body, delay_days}]
    social_account_id: int


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/import-url")
async def import_single_url(
    payload: ImportURLRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Import a single LinkedIn profile URL, enrich it, and create a lead."""
    service = LinkedInEnrichmentService()
    results = await service.bulk_import_leads(
        db=db,
        company_id=current_user.company_id,
        linkedin_urls=[payload.linkedin_url],
    )
    if not results:
        raise HTTPException(status_code=400, detail="No results returned")
    result = results[0]
    if result["status"] == "failed":
        raise HTTPException(status_code=400, detail=result.get("error", "Import failed"))
    return result


@router.post("/bulk-import")
async def bulk_import(
    payload: BulkImportRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Import multiple LinkedIn URLs and create leads for each."""
    if not payload.linkedin_urls:
        raise HTTPException(status_code=400, detail="No URLs provided")
    if len(payload.linkedin_urls) > 100:
        raise HTTPException(status_code=400, detail="Maximum 100 URLs per request")

    service = LinkedInEnrichmentService()
    results = await service.bulk_import_leads(
        db=db,
        company_id=current_user.company_id,
        linkedin_urls=payload.linkedin_urls,
    )

    successful = [r for r in results if r["status"] == "success"]
    failed = [r for r in results if r["status"] == "failed"]

    return {
        "total": len(results),
        "successful": len(successful),
        "failed": len(failed),
        "results": results,
    }


@router.post("/bulk-import-csv")
async def bulk_import_csv(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Import LinkedIn URLs from a CSV file. Expects a column named 'linkedin_url'."""
    if not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="File must be a CSV")

    content = await file.read()
    reader = csv.DictReader(io.StringIO(content.decode("utf-8", errors="replace")))

    urls = []
    for row in reader:
        url = row.get("linkedin_url") or row.get("LinkedIn URL") or row.get("url", "")
        if url and "linkedin.com" in url:
            urls.append(url.strip())

    if not urls:
        raise HTTPException(
            status_code=400,
            detail="No LinkedIn URLs found. CSV must have a 'linkedin_url' column."
        )

    service = LinkedInEnrichmentService()
    results = await service.bulk_import_leads(
        db=db,
        company_id=current_user.company_id,
        linkedin_urls=urls[:100],
    )

    return {
        "total": len(results),
        "successful": len([r for r in results if r["status"] == "success"]),
        "failed": len([r for r in results if r["status"] == "failed"]),
        "results": results,
    }


@router.post("/enrich/{contact_id}")
async def enrich_contact(
    contact_id: int,
    payload: EnrichContactRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Re-enrich an existing contact from their stored LinkedIn URL."""
    contact = db.query(Contact).filter(
        Contact.id == contact_id,
        Contact.company_id == current_user.company_id,
    ).first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    if not contact.linkedin_url:
        raise HTTPException(status_code=400, detail="Contact has no LinkedIn URL")

    service = LinkedInEnrichmentService()
    enrichment = await service.enrich_from_url(
        db=db,
        company_id=current_user.company_id,
        linkedin_url=contact.linkedin_url,
        social_account_id=payload.social_account_id,
    )

    # Apply enrichment to contact
    from datetime import datetime
    for field in ["job_title", "company_name", "industry", "location"]:
        if enrichment.get(field):
            setattr(contact, field, enrichment[field])
    contact.enriched_at = datetime.utcnow()
    contact.enrichment_source = enrichment.get("enrichment_source", "ai_knowledge")
    db.commit()

    return {"contact_id": contact_id, "enrichment": enrichment}


@router.post("/outreach", status_code=status.HTTP_201_CREATED)
def create_linkedin_outreach(
    payload: LinkedInOutreachRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Create a LinkedIn outreach campaign for selected contacts.
    Enrolls contacts and sets up DM message sequence.
    """
    from app.models.campaign import Campaign, CampaignType, CampaignStatus
    from app.models.campaign_message import CampaignMessage, MessageType, DelayUnit
    from app.models.campaign_contact import CampaignContact

    # Validate contacts belong to company
    contacts = db.query(Contact).filter(
        Contact.id.in_(payload.contact_ids),
        Contact.company_id == current_user.company_id,
    ).all()
    if not contacts:
        raise HTTPException(status_code=404, detail="No valid contacts found")

    # Warn about contacts missing linkedin_urn (outreach will skip them at send time)
    missing_urn = [c.id for c in contacts if not c.linkedin_urn]

    # Create campaign
    campaign = Campaign(
        name=payload.name,
        company_id=current_user.company_id,
        campaign_type=CampaignType.LINKEDIN,
        status=CampaignStatus.DRAFT,
        created_by_user_id=current_user.id,
    )
    db.add(campaign)
    db.flush()

    # Create message sequence
    for i, msg in enumerate(payload.messages, start=1):
        message = CampaignMessage(
            campaign_id=campaign.id,
            sequence_order=i,
            message_type=MessageType.LINKEDIN_DM,
            name=msg.get("subject", f"Step {i}"),
            body=msg.get("body", ""),
            delay_amount=msg.get("delay_days", 0),
            delay_unit=DelayUnit.DAYS,
        )
        db.add(message)

    # Enroll contacts
    for contact in contacts:
        enrollment = CampaignContact(
            campaign_id=campaign.id,
            contact_id=contact.id,
        )
        db.add(enrollment)

    db.commit()
    db.refresh(campaign)

    return {
        "campaign_id": campaign.id,
        "campaign_name": campaign.name,
        "enrolled_contacts": len(contacts),
        "missing_linkedin_urn": missing_urn,
        "warning": (
            f"{len(missing_urn)} contact(s) have no LinkedIn URN and will be skipped at send time."
            if missing_urn else None
        ),
    }


@router.get("/leads")
def list_linkedin_leads(
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List leads imported from LinkedIn with enriched contact data."""
    leads = (
        db.query(Lead)
        .join(Contact, Lead.contact_id == Contact.id)
        .filter(
            Lead.company_id == current_user.company_id,
            Lead.source == "linkedin_import",
        )
        .order_by(Lead.id.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    result = []
    for lead in leads:
        contact = lead.contact
        result.append({
            "lead_id": lead.id,
            "contact_id": contact.id,
            "name": contact.name,
            "email": contact.email,
            "job_title": contact.job_title,
            "company_name": contact.company_name,
            "industry": contact.industry,
            "location": contact.location,
            "linkedin_url": contact.linkedin_url,
            "linkedin_urn": contact.linkedin_urn,
            "enriched_at": contact.enriched_at,
            "enrichment_source": contact.enrichment_source,
            "lead_stage": lead.stage,
            "lead_score": lead.score,
            "created_at": lead.created_at if hasattr(lead, "created_at") else None,
        })

    return {"total": len(result), "leads": result}
