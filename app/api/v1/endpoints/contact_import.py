import csv
import io
from typing import List

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, get_current_active_user
from app.models.contact import Contact
from app.models.lead import Lead, LeadStage
from app.models.user import User

router = APIRouter()

# Maps CSV header names (lowercased/stripped) to a canonical key
_HEADER_MAP = {
    "email": "email",
    "name": "name",
    "first_name": "first_name",
    "firstname": "first_name",
    "last_name": "last_name",
    "lastname": "last_name",
    "phone": "phone_number",
    "phone_number": "phone_number",
    "company": "company_name",
    "company_name": "company_name",
    "job_title": "job_title",
    "jobtitle": "job_title",
    "lead_source": "lead_source",
    "leadsource": "lead_source",
    "lifecycle_stage": "lifecycle_stage",
    "lifecyclestage": "lifecycle_stage",
}


@router.post("/import")
async def import_contacts(
    file: UploadFile = File(...),
    create_leads: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """
    Bulk-import contacts from a CSV file.

    - Upserts contacts by email within the authenticated user's company.
    - If ``create_leads=true``, also creates a Lead record (source="import")
      for each **new** contact.
    - Returns a summary of created, updated, skipped, and errored rows.
    """
    raw = await file.read()
    content = raw.decode("utf-8")
    reader = csv.DictReader(io.StringIO(content))

    # Normalise header names once
    if reader.fieldnames is None:
        return {"created": 0, "updated": 0, "skipped": 0, "errors": []}

    canonical_headers: dict[str, str] = {}
    for original in reader.fieldnames:
        norm = original.strip().lower()
        if norm in _HEADER_MAP:
            canonical_headers[original] = _HEADER_MAP[norm]

    company_id = current_user.company_id

    created = 0
    updated = 0
    skipped = 0
    errors: List[dict] = []

    rows = list(reader)

    for row_index, raw_row in enumerate(rows, start=2):  # row 1 is the header
        try:
            # Re-key the row using canonical names; non-mapped columns are ignored
            row: dict = {}
            for original_key, value in raw_row.items():
                if original_key in canonical_headers:
                    row[canonical_headers[original_key]] = (value or "").strip()

            # Combine first_name + last_name → name if explicit "name" not present
            if "name" not in row or not row["name"]:
                first = row.get("first_name", "")
                last = row.get("last_name", "")
                combined = " ".join(part for part in (first, last) if part)
                if combined:
                    row["name"] = combined

            email = row.get("email", "")
            name = row.get("name", "")

            # Skip rows with nothing useful
            if not email and not name:
                skipped += 1
                continue

            # Upsert logic — look up by email within this company
            existing: Contact | None = None
            if email:
                existing = (
                    db.query(Contact)
                    .filter(
                        Contact.email == email,
                        Contact.company_id == company_id,
                    )
                    .first()
                )

            if existing:
                # Update — only overwrite fields that are present & non-empty in the CSV
                if name:
                    existing.name = name
                if row.get("phone_number"):
                    existing.phone_number = row["phone_number"]
                if row.get("company_name"):
                    existing.company_name = row["company_name"]
                if row.get("job_title"):
                    existing.job_title = row["job_title"]
                if row.get("lead_source"):
                    existing.lead_source = row["lead_source"]
                if row.get("lifecycle_stage"):
                    existing.lifecycle_stage = row["lifecycle_stage"]
                updated += 1
            else:
                # Create new contact
                new_contact = Contact(
                    company_id=company_id,
                    email=email or None,
                    name=name or None,
                    phone_number=row.get("phone_number") or None,
                    company_name=row.get("company_name") or None,
                    job_title=row.get("job_title") or None,
                    lead_source=row.get("lead_source") or None,
                    lifecycle_stage=row.get("lifecycle_stage") or None,
                )
                db.add(new_contact)
                db.flush()  # populate new_contact.id without full commit

                if create_leads:
                    new_lead = Lead(
                        contact_id=new_contact.id,
                        company_id=company_id,
                        source="import",
                        stage=LeadStage.LEAD,
                    )
                    db.add(new_lead)

                created += 1

        except Exception as exc:  # noqa: BLE001
            errors.append({"row": row_index, "reason": str(exc)})

    db.commit()

    return {
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "errors": errors,
    }
