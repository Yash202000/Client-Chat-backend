"""
Data Export Endpoint

Generates a ZIP archive of the company's data as CSV files and streams it
back to the client.
"""
import csv
import io
import zipfile
from datetime import date
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, get_current_active_user
from app.models.user import User

router = APIRouter()


def _rows_to_csv_bytes(headers: list, rows: list) -> bytes:
    """Serialize a list of dicts to CSV bytes."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=headers, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8")


@router.post("/data")
async def export_all_data(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """
    Generate and return a ZIP file containing CSVs of all company data:
    contacts, leads, deals, campaigns, sequences, tickets, and templates.
    """
    company_id = current_user.company_id

    # ------------------------------------------------------------------
    # Contacts
    # ------------------------------------------------------------------
    from app.models.contact import Contact

    contacts_rows = []
    for c in db.query(Contact).filter(Contact.company_id == company_id).all():
        contacts_rows.append(
            {
                "id": c.id,
                "name": c.name,
                "email": c.email,
                "phone_number": c.phone_number,
                "lifecycle_stage": c.lifecycle_stage,
                "lead_source": c.lead_source,
                "do_not_contact": c.do_not_contact,
                "opt_in_status": c.opt_in_status,
                "created_at": c.created_at,
            }
        )
    contacts_csv = _rows_to_csv_bytes(
        ["id", "name", "email", "phone_number", "lifecycle_stage",
         "lead_source", "do_not_contact", "opt_in_status", "created_at"],
        contacts_rows,
    )

    # ------------------------------------------------------------------
    # Leads
    # ------------------------------------------------------------------
    from app.models.lead import Lead

    leads_rows = []
    for l in db.query(Lead).filter(Lead.company_id == company_id).all():
        leads_rows.append(
            {
                "id": l.id,
                "contact_id": l.contact_id,
                "source": l.source,
                "stage": l.stage,
                "qualification_status": l.qualification_status,
                "assignee_id": l.assignee_id,
                "campaign_id": l.campaign_id,
                "created_at": l.created_at,
            }
        )
    leads_csv = _rows_to_csv_bytes(
        ["id", "contact_id", "source", "stage", "qualification_status",
         "assignee_id", "campaign_id", "created_at"],
        leads_rows,
    )

    # ------------------------------------------------------------------
    # Deals
    # ------------------------------------------------------------------
    from app.models.deal import Deal

    deals_rows = []
    for d in db.query(Deal).filter(Deal.company_id == company_id).all():
        deals_rows.append(
            {
                "id": d.id,
                "title": d.title,
                "amount": d.amount,
                "currency": d.currency,
                "status": d.status,
                "pipeline_id": d.pipeline_id,
                "stage_id": d.stage_id,
                "contact_id": d.contact_id,
                "account_id": d.account_id,
                "owner_id": d.owner_id,
                "expected_close_date": d.expected_close_date,
                "actual_close_date": d.actual_close_date,
                "created_at": d.created_at,
            }
        )
    deals_csv = _rows_to_csv_bytes(
        ["id", "title", "amount", "currency", "status", "pipeline_id",
         "stage_id", "contact_id", "account_id", "owner_id",
         "expected_close_date", "actual_close_date", "created_at"],
        deals_rows,
    )

    # ------------------------------------------------------------------
    # Campaigns
    # ------------------------------------------------------------------
    from app.models.campaign import Campaign

    campaigns_rows = []
    for c in db.query(Campaign).filter(Campaign.company_id == company_id).all():
        campaigns_rows.append(
            {
                "id": c.id,
                "name": c.name,
                "type": c.type,
                "status": c.status,
                "created_at": c.created_at,
            }
        )
    campaigns_csv = _rows_to_csv_bytes(
        ["id", "name", "type", "status", "created_at"],
        campaigns_rows,
    )

    # ------------------------------------------------------------------
    # Sequences
    # ------------------------------------------------------------------
    from app.models.sequence import Sequence

    sequences_rows = []
    for s in db.query(Sequence).filter(Sequence.company_id == company_id).all():
        sequences_rows.append(
            {
                "id": s.id,
                "name": s.name,
                "description": s.description,
                "status": s.status,
                "goal": s.goal,
                "created_at": s.created_at,
            }
        )
    sequences_csv = _rows_to_csv_bytes(
        ["id", "name", "description", "status", "goal", "created_at"],
        sequences_rows,
    )

    # ------------------------------------------------------------------
    # Tickets (optional table — may not exist)
    # ------------------------------------------------------------------
    tickets_csv = b"id,subject,status,priority,contact_id,created_at\n"
    try:
        from sqlalchemy import text

        rows = db.execute(
            text(
                "SELECT id, subject, status, priority, contact_id, created_at "
                "FROM tickets WHERE company_id = :cid"
            ),
            {"cid": company_id},
        ).fetchall()
        if rows:
            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow(["id", "subject", "status", "priority", "contact_id", "created_at"])
            for row in rows:
                writer.writerow(list(row))
            tickets_csv = buf.getvalue().encode("utf-8")
    except Exception:
        # Table does not exist yet — emit empty CSV with headers only
        pass

    # ------------------------------------------------------------------
    # Templates
    # ------------------------------------------------------------------
    from app.models.template import Template

    templates_rows = []
    for t in db.query(Template).filter(Template.company_id == company_id).all():
        templates_rows.append(
            {
                "id": t.id,
                "name": t.name,
                "type": t.type,
                "description": t.description,
                "created_at": t.created_at,
            }
        )
    templates_csv = _rows_to_csv_bytes(
        ["id", "name", "type", "description", "created_at"],
        templates_rows,
    )

    # ------------------------------------------------------------------
    # Build ZIP in memory
    # ------------------------------------------------------------------
    zip_buffer = io.BytesIO()
    today = date.today().isoformat()

    with zipfile.ZipFile(zip_buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("contacts.csv", contacts_csv)
        zf.writestr("leads.csv", leads_csv)
        zf.writestr("deals.csv", deals_csv)
        zf.writestr("campaigns.csv", campaigns_csv)
        zf.writestr("sequences.csv", sequences_csv)
        zf.writestr("tickets.csv", tickets_csv)
        zf.writestr("templates.csv", templates_csv)

    zip_buffer.seek(0)

    filename = f"export_{today}.zip"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}

    return StreamingResponse(
        iter([zip_buffer.read()]),
        media_type="application/zip",
        headers=headers,
    )
